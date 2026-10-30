"""End-to-end contract test: the real FastAPI backend (in-process, SQLite) driven by the real GPU
worker loop with the deterministic fake engines.

It proves the two halves agree on the whole protocol - registration, leasing, blob access,
heartbeats, artifact upload, result schemas - and that every GPU result lands where the web app
reads it: OCR text on pages, translations on chunks, captions on photos, and a 3D twin on the site.
Skipped when the backend is not importable (e.g. the worker is installed on its own in Colab).
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("app.main", reason="backend package not importable")

from app.core.config import Settings
from app.main import create_app
from fastapi.testclient import TestClient

from heritage_gpu.client import ApiClient
from heritage_gpu.config import WorkerConfig
from heritage_gpu.engines import build_engines
from heritage_gpu.runner import Runner, RunStats
from heritage_gpu.selftest import synthetic_page, synthetic_photo

API = "/api/v1"
WORKER_TOKEN = "contract-worker-token"
INGEST = {"Authorization": "Bearer contract-ingest-token"}
SITE = {
    "slug": "rani-ki-vav",
    "name": "Rani ki Vav",
    "category": "stepwell",
    "state": "Gujarat",
    "lat": 23.8589,
    "lon": 72.1016,
    "summary": "An 11th-century stepwell in Patan.",
}
GUJARATI_NOTE = (
    "રાણકી વાવ પાટણમાં આવેલી અગિયારમી સદીની પગથિયાંવાળી વાવ છે. "
    "તેની દીવાલો પર વિષ્ણુના અવતારો અને અપ્સરાઓની સુંદર કોતરણી જોવા મળે છે."
)


@pytest.fixture
def api(tmp_path: Path) -> Iterator[TestClient]:
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'contract.db').as_posix()}",
        storage_dir=tmp_path / "storage",
        embedder="hashing",
        enable_image_search=False,
        embedded_worker=True,  # CPU stages (extract, index) run inside the app
        gpu_fallback_to_cpu=False,  # ... and every GPU stage must go through the remote worker
        worker_poll_seconds=0.05,
        worker_token=WORKER_TOKEN,
        ingest_token="contract-ingest-token",
        log_level="WARNING",
    )
    with TestClient(create_app(settings)) as client:
        yield client


def _upload(api: TestClient, name: str, data: bytes, mime: str, **form: Any) -> int:
    r = api.post(
        f"{API}/assets",
        files=[("files", (name, data, mime))],
        data={k: str(v) for k, v in form.items()},
        headers=INGEST,
    )
    assert r.status_code == 201, r.text
    return int(r.json()[0]["asset"]["id"])


def _wait(what: str, probe: Callable[[], Any], timeout: float = 60.0) -> Any:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = probe()
        if value:
            return value
        time.sleep(0.1)
    raise AssertionError(f"timed out waiting for {what}")


def _start_worker(api: TestClient) -> tuple[Runner, threading.Thread, list[RunStats]]:
    config = WorkerConfig.from_env(
        {},
        api_url=f"http://testserver{API}",
        token=WORKER_TOKEN,
        name="Contract GPU",
        fake=True,
        lease_seconds=60,
        heartbeat_seconds=0.5,
        poll_min_seconds=0.02,
        poll_max_seconds=0.1,
    )
    client = ApiClient(config.base_url, config.token, http=api, retries=0)
    runner = Runner(config, client=client, engines=build_engines(config))
    stats: list[RunStats] = []
    thread = threading.Thread(target=lambda: stats.append(runner.run()), name="gpu-worker", daemon=True)
    thread.start()
    return runner, thread, stats


def test_fake_gpu_worker_completes_every_pathway_against_the_real_api(api: TestClient) -> None:
    r = api.post(f"{API}/sites", json=SITE, headers=INGEST)
    assert r.status_code == 201, r.text
    site_id = r.json()["id"]

    runner, thread, stats = _start_worker(api)
    try:
        scan = _upload(api, "letter-1932.png", synthetic_page(), "image/png", kind="scan", site_id=site_id)
        note = _upload(api, "nondh.txt", GUJARATI_NOTE.encode(), "text/plain", site_id=site_id)
        photo = _upload(api, "pavilion.png", synthetic_photo(), "image/png", kind="photo", site_id=site_id)

        def asset(asset_id: int) -> dict[str, Any]:
            body: dict[str, Any] = api.get(f"{API}/assets/{asset_id}").json()
            return body

        # Pathway 1a - OCR of a scanned page (GPU), then CPU indexing.
        scanned = _wait("OCR", lambda: (a := asset(scan))["status"] == "ready" and a["pages"][0]["ocr_engine"] and a)
        assert scanned["pages"][0]["ocr_engine"] == "fake-ocr"
        text = api.get(f"{API}/assets/{scan}/pages/1/text").json()
        assert "Synthetic transcription of page 1" in str(text)

        # Pathway 1b - Gujarati text is translated (GPU) and re-indexed with the gloss.
        def translated() -> list[dict[str, Any]]:
            chunks: list[dict[str, Any]] = api.get(f"{API}/assets/{note}/chunks").json()
            return chunks if chunks and all(c["translation"] for c in chunks) else []

        chunks = _wait("translation", translated)
        assert all(c["translation"].startswith("[synthetic Gujarati gloss]") for c in chunks)
        assert {c["translation_engine"] for c in chunks} == {"fake-translate"}
        assert _wait("translated ratio", lambda: asset(note)["translated_ratio"] == 1.0)

        # Pathway 2 - an uncaptioned photo is captioned (GPU) and becomes searchable by the caption.
        captioned = _wait("caption", lambda: (a := asset(photo))["caption_source"] and a)
        assert captioned["caption_source"] == "fake-caption" and "synthetic caption" in captioned["caption"]
        hits = _wait(
            "caption search",
            lambda: api.get(f"{API}/search", params={"q": "synthetic caption photograph"}).json()["hits"],
        )
        assert hits[0]["asset"]["id"] == photo

        # Pathway 3 - a digital twin is reconstructed (GPU), uploaded as an artifact and served.
        r = api.post(
            f"{API}/sites/rani-ki-vav/twins", json={"asset_ids": [photo], "title": "Pavilion relief"}, headers=INGEST
        )
        assert r.status_code == 202, r.text
        [twin] = _wait("twin", lambda: api.get(f"{API}/sites/rani-ki-vav/twins").json())
        assert twin["method"] == "luminance-relief" and twin["format"] == "ply"
        assert twin["title"] == "Pavilion relief" and twin["source_asset_ids"] == [photo]
        model = api.get(f"{API}/twins/{twin['id']}/file")
        assert model.status_code == 200 and model.content.startswith(b"ply\n")
        assert f"element vertex {twin['point_count']}".encode() in model.content[:400]
    finally:
        runner.stop()
        thread.join(timeout=15)

    assert not thread.is_alive(), "worker did not stop"
    [run] = stats
    assert run.failed == 0 and run.lost == 0 and run.succeeded >= 4
    [gpu] = [w for w in api.get(f"{API}/workers").json() if w["queue"] == "gpu"]
    assert gpu["name"] == "Contract GPU" and gpu["jobs_done"] == run.succeeded and gpu["jobs_failed"] == 0
    queued = api.get(f"{API}/jobs", params={"queue": "gpu", "status": "queued"}).json()["items"]
    assert queued == []
