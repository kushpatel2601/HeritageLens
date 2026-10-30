from __future__ import annotations

import io
from typing import Any

import pytest
from PIL import Image

from heritage_gpu.config import ALL_JOB_TYPES, WorkerConfig
from heritage_gpu.engines import Engine, JobIO, build_engines, decode_image
from heritage_gpu.engines.fake import FAKE_ENGINES, luminance_disparity
from heritage_gpu.errors import JobError
from heritage_gpu.selftest import MemoryIO, payloads, run_selftest


def _encode(img: Image.Image, fmt: str = "PNG", **kw: Any) -> bytes:
    buf = io.BytesIO()
    img.save(buf, fmt, **kw)
    return buf.getvalue()


# ---------------------------------------------------------------- image decoding
def test_decode_image_applies_exif_orientation_and_bounds_size() -> None:
    exif = Image.Exif()
    exif[0x0112] = 6  # "rotate 90 CW": phones store portraits like this
    data = _encode(Image.new("RGB", (400, 200), "red"), "JPEG", exif=exif)
    assert decode_image(data).size == (200, 400)
    assert decode_image(data, max_side=100).size == (50, 100)
    assert decode_image(_encode(Image.new("LA", (8, 8)))).mode == "RGB"


@pytest.mark.parametrize("data", [b"", b"not an image", b"\x89PNG\r\n\x1a\n" + b"\0" * 32])
def test_decode_image_rejects_garbage_permanently(data: bytes) -> None:
    with pytest.raises(JobError) as err:
        decode_image(data)
    assert err.value.retryable is False


def test_decode_image_refuses_decompression_bombs() -> None:
    bomb = _encode(Image.new("1", (9000, 9000)))  # 81 MP of bilevel zeros compresses to a few KB
    assert len(bomb) < 100_000
    with pytest.raises(JobError, match="too large") as err:
        decode_image(bomb)
    assert err.value.retryable is False


# ---------------------------------------------------------------- engine registry
def test_real_engines_are_constructed_lazily_without_ml_dependencies() -> None:
    engines = build_engines(WorkerConfig.from_env({}))
    assert {t: type(e).__name__ for t, e in engines.items()} == {
        "ocr": "TesseractOCR",
        "translate": "AutoTranslator",
        "caption": "BlipCaptioner",
        "reconstruct3d": "Reconstructor",
    }
    alt = build_engines(WorkerConfig.from_env({}, ocr_engine="vlm", translator="nllb", job_types=("ocr", "translate")))
    assert [type(e).__name__ for e in alt.values()] == ["VlmOCR", "NllbTranslator"]


@pytest.mark.parametrize("overrides", [{"ocr_engine": "abbyy"}, {"translator": "google"}])
def test_unknown_engine_choices_are_rejected(overrides: dict[str, str]) -> None:
    with pytest.raises(ValueError, match="unknown"):
        build_engines(WorkerConfig.from_env({}, **overrides))


def test_fake_registry_honours_job_types() -> None:
    engines = build_engines(WorkerConfig.from_env({}, fake=True, job_types=("caption", "ocr")))
    assert list(engines) == ["caption", "ocr"]
    assert {cls.job_type for cls in FAKE_ENGINES} == set(ALL_JOB_TYPES)


# ---------------------------------------------------------------- fake engines vs. the server's schemas
def _run(engine: Engine, job_type: str) -> tuple[dict[str, Any], MemoryIO]:
    blobs, jobs = payloads()
    memio = MemoryIO(blobs, job_id=42)
    engine.ensure_loaded()
    return engine.run(jobs[job_type], memio), memio


@pytest.mark.parametrize("engine_cls", FAKE_ENGINES, ids=lambda c: c.job_type)
def test_fake_results_satisfy_the_server_result_schemas(engine_cls: type[Engine]) -> None:
    schemas = pytest.importorskip("app.schemas.worker", reason="backend not importable")
    model = {
        "ocr": schemas.OcrResult,
        "translate": schemas.TranslateResult,
        "caption": schemas.CaptionResult,
        "reconstruct3d": schemas.ReconstructResult,
    }[engine_cls.job_type]
    result, _ = _run(engine_cls(), engine_cls.job_type)
    model.model_validate(result)


def test_fake_translator_skips_empty_items_and_labels_languages() -> None:
    from heritage_gpu.engines.fake import FakeTranslator

    payload = {
        "src_lang": "hi",
        "items": [
            {"chunk_id": 1, "text": "  "},
            {"chunk_id": 2, "text": "नमस्ते"},
            {"chunk_id": 3, "text": "x", "lang": "gu"},
        ],
    }
    result = FakeTranslator().run(payload, MemoryIO({}))
    assert result["items"] == [
        {"chunk_id": 2, "translation": "[synthetic Hindi gloss] नमस्ते"},
        {"chunk_id": 3, "translation": "[synthetic Gujarati gloss] x"},
    ]


def test_fake_relief_uploads_a_ply_artifact() -> None:
    from heritage_gpu.engines.fake import FakeReconstructor

    result, memio = _run(FakeReconstructor(), "reconstruct3d")
    [(key, data)] = memio.artifacts.items()
    assert result["artifact_key"] == key and key.endswith("relief-0.ply")
    assert data.startswith(b"ply\n") and f"element vertex {result['point_count']}".encode() in data
    assert 1_000 < result["point_count"] <= 60_000 and result["title"] == "Self-test relief"


def test_luminance_disparity_favours_bright_and_lower_pixels() -> None:
    import numpy as np

    rgb = np.zeros((100, 100, 3), np.uint8)
    rgb[:, 50:] = 255
    d = luminance_disparity(rgb)
    assert d.shape == (100, 100)
    assert d[50, 90] > d[50, 10]  # brighter = nearer
    assert d[95, 10] > d[5, 10]  # lower in frame = nearer (ground plane)


# ---------------------------------------------------------------- self-test
def test_selftest_reports_every_engine(capsys: pytest.CaptureFixture[str]) -> None:
    assert run_selftest(build_engines(WorkerConfig.from_env({}, fake=True))) is True
    lines = capsys.readouterr().out.splitlines()
    assert [line.split()[:2] for line in lines] == [["ok", t] for t in ALL_JOB_TYPES]


def test_selftest_fails_when_an_engine_fails(capsys: pytest.CaptureFixture[str]) -> None:
    class Broken(Engine):
        job_type = "caption"

        @property
        def name(self) -> str:
            return "broken"

        def load(self) -> None:
            raise OSError("model weights not found")

        def run(self, payload: dict[str, Any], io: JobIO) -> dict[str, Any]:
            raise AssertionError("unreachable")

    assert run_selftest({"caption": Broken()}) is False
    assert "FAIL caption" in capsys.readouterr().out
