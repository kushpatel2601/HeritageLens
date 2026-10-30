from __future__ import annotations

from pathlib import Path

import pytest

from heritage_gpu.config import ALL_JOB_TYPES, WorkerConfig, api_base
from heritage_gpu.langs import FLORES, NAMES, TESSERACT, langs_for_script, tesseract_langs


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://x.trycloudflare.com", "https://x.trycloudflare.com/api/v1"),
        ("https://x.trycloudflare.com/", "https://x.trycloudflare.com/api/v1"),
        ("http://localhost:8000/api/v1/", "http://localhost:8000/api/v1"),
        (" http://10.0.0.2:8000/api/v2 ", "http://10.0.0.2:8000/api/v2"),
    ],
)
def test_api_base_accepts_root_or_versioned_urls(url: str, expected: str) -> None:
    assert api_base(url) == expected


def test_api_base_rejects_schemeless_urls() -> None:
    with pytest.raises(ValueError, match="http"):
        api_base("x.trycloudflare.com")


def test_from_env_coerces_types_and_cli_overrides_win() -> None:
    env = {
        "HERITAGE_API_URL": "https://tunnel.example",
        "HERITAGE_TOKEN": "s3cret",
        "HERITAGE_FAKE": "yes",
        "HERITAGE_JOB_TYPES": "ocr, caption",
        "HERITAGE_LEASE_SECONDS": "600",
        "HERITAGE_HEARTBEAT_SECONDS": "45.5",
        "HERITAGE_WORK_DIR": "/tmp/hl",
        "HERITAGE_MAX_JOBS": "",  # empty means unset
        "UNRELATED": "1",
    }
    cfg = WorkerConfig.from_env(env, name="kaggle-p100", token=None, splat_steps=3000)
    assert cfg.base_url == "https://tunnel.example/api/v1"
    assert cfg.token == "s3cret"  # None overrides are ignored
    assert cfg.fake is True and cfg.job_types == ("ocr", "caption")
    assert cfg.lease_seconds == 600 and cfg.heartbeat_seconds == 45.5
    assert cfg.work_dir == Path("/tmp/hl") and cfg.max_jobs is None
    assert cfg.name == "kaggle-p100" and cfg.splat_steps == 3000


def test_defaults_cover_every_job_type() -> None:
    cfg = WorkerConfig.from_env({})
    assert cfg.job_types == ALL_JOB_TYPES and cfg.fake is False
    assert cfg.heartbeat_seconds < cfg.lease_seconds


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"job_types": ("ocr", "summarise")}, "unknown job types"),
        ({"job_types": ()}, "at least one"),
        ({"lease_seconds": 60, "heartbeat_seconds": 60}, "heartbeat"),
        ({"lease_seconds": 7200, "heartbeat_seconds": 60}, "between 30 and 3600"),
        ({"api_url": "ftp://archive"}, "http"),
    ],
)
def test_config_validation(overrides: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        WorkerConfig.from_env({}, **overrides)


def test_language_tables_are_consistent() -> None:
    assert set(FLORES) == set(TESSERACT) == set(NAMES)


@pytest.mark.parametrize(
    ("hint", "available", "expected"),
    [
        ("gu", {"guj", "hin", "eng"}, "guj+eng"),
        ("en", {"guj", "hin", "eng"}, "eng"),
        ("mr", {"hin", "eng"}, "eng"),  # model missing: still read the Latin annotations
        (None, {"guj", "eng", "osd"}, "guj+eng"),  # default restricted to what is installed
        ("xx", {"hin"}, "hin"),
        (None, {"tam"}, "tam"),  # nothing from the default installed
        (None, set(), "eng"),
    ],
)
def test_tesseract_langs(hint: str | None, available: set[str], expected: str) -> None:
    assert tesseract_langs(hint, available) == expected


@pytest.mark.parametrize(
    ("script", "available", "expected"),
    [
        ("Devanagari", {"hin", "mar", "eng"}, "hin+eng"),
        ("Devanagari", {"mar", "eng"}, "mar+eng"),
        ("Devanagari", {"san"}, "san"),
        ("Gujarati", {"guj", "eng"}, "guj+eng"),
        ("Latin", {"guj", "eng"}, "eng"),
        ("Tamil", {"guj", "eng"}, None),
        ("Klingon", {"eng"}, None),
        (None, {"eng"}, None),
    ],
)
def test_langs_for_script(script: str | None, available: set[str], expected: str | None) -> None:
    assert langs_for_script(script, available) == expected
