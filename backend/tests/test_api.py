"""HTTP contract tests: the REST surface the web app uses and the pull-based protocol remote GPU
workers (Colab) speak, exercised end-to-end through the real ASGI app and its embedded CPU worker."""

from __future__ import annotations

import io
import time
from typing import Any

import numpy as np
from fastapi.testclient import TestClient
from PIL import Image

from app.services.twins import vav_stepwell, write_ply
from tests.conftest import INGEST_TOKEN, WORKER_TOKEN, wait_for_asset

API = "/api/v1"
INGEST = {"Authorization": f"Bearer {INGEST_TOKEN}"}
WORKER = {"Authorization": f"Bearer {WORKER_TOKEN}"}
SITE = {
    "slug": "rani-ki-vav",
    "name": "Rani ki Vav",
    "name_native": "रानी की वाव",
    "alt_names": ["Queen's Stepwell"],
    "category": "stepwell",
    "state": "Gujarat",
    "lat": 23.8589,
    "lon": 72.1016,
    "summary": "An 11th-century stepwell in Patan.",
}
JOURNAL = (
    "Field notes from Rani ki Vav, Patan, written in 1998.\n\n"
    "The stepwell was silted up until the excavations; the sculpted panels show Vishnu avatars."
)


def _jpeg(seed: int) -> bytes:
    rng = np.random.default_rng(seed)
    buf = io.BytesIO()
    small = Image.fromarray(rng.integers(0, 255, (6, 8, 3), dtype=np.uint8))
    small.resize((320, 240), Image.Resampling.BICUBIC).save(buf, "JPEG", quality=90)
    return buf.getvalue()


def _create_site(client: TestClient) -> dict[str, Any]:
    r = client.post(f"{API}/sites", json=SITE, headers=INGEST)
    assert r.status_code == 201, r.text
    return r.json()


def _upload(client: TestClient, name: str, data: bytes, mime: str, **form: Any) -> dict[str, Any]:
    r = client.post(
        f"{API}/assets",
        files=[("files", (name, data, mime))],
        data={k: str(v) for k, v in form.items()},
        headers=INGEST,
    )
    assert r.status_code == 201, r.text
    [result] = r.json()
    return result


def _register(client: TestClient, *capabilities: str) -> str:
    r = client.post(
        f"{API}/workers/register",
        json={"name": "Colab T4", "queue": "gpu", "device": "Tesla T4", "capabilities": list(capabilities)},
        headers=WORKER,
    )
    assert r.status_code == 200, r.text
    worker = r.json()
    assert worker["id"].startswith("gpu-colab-t4-") and worker["online"] is True
    return str(worker["id"])


def _lease(client: TestClient, worker_id: str, **body: Any) -> list[dict[str, Any]]:
    r = client.post(f"{API}/workers/{worker_id}/lease", json=body, headers=WORKER)
    assert r.status_code == 200, r.text
    return list(r.json()["jobs"])


def _problem(r: Any, status: int) -> dict[str, Any]:
    assert r.status_code == status, r.text
    assert r.headers["content-type"].startswith("application/problem+json")
    body: dict[str, Any] = r.json()
    assert body["status"] == status and body["title"] and "instance" in body
    return body


# ---------------------------------------------------------------- ops & error contract
def test_health_readiness_and_openapi(client: TestClient) -> None:
    assert client.get(f"{API}/health").json() == {"status": "ok"}

    r = client.get(f"{API}/ready", headers={"X-Request-ID": "trace-123"})
    assert r.status_code == 200
    assert r.headers["x-request-id"] == "trace-123" and "server-timing" in r.headers
    ready = r.json()
    assert ready["status"] == "ok" and ready["database"] == "sqlite" and ready["embedder"].startswith("hashing")
    assert ready["checks"]["gpu_workers"].startswith("none online")

    paths = client.get(f"{API}/openapi.json").json()["paths"]
    for path in ("/api/v1/search", "/api/v1/assets", "/api/v1/workers/{worker_id}/lease", "/api/v1/sites/{slug}/twins"):
        assert path in paths

    stats = client.get(f"{API}/stats").json()
    assert stats["assets"] == 0 and stats["database"] == "sqlite"


def test_errors_are_problem_json(client: TestClient) -> None:
    body = _problem(client.get(f"{API}/assets/424242"), 404)
    assert body["instance"] == f"{API}/assets/424242" and body["request_id"]

    body = _problem(client.get(f"{API}/search"), 422)
    assert body["title"] == "Validation failed" and body["detail"][0]["loc"] == ["query", "q"]

    _problem(client.get(f"{API}/search", params={"q": "vav", "bbox": "1,2,3"}), 422)
    _problem(client.get(f"{API}/sites/no-such-site"), 404)


def test_writes_require_the_ingest_token(client: TestClient) -> None:
    files = [("files", ("notes.txt", b"hello", "text/plain"))]
    _problem(client.post(f"{API}/assets", files=files), 401)
    _problem(client.post(f"{API}/assets", files=files, headers={"Authorization": "Bearer wrong"}), 401)
    _problem(client.post(f"{API}/sites", json=SITE), 401)
    assert client.get(f"{API}/sites").json() == []  # reads stay public


def test_site_validation_and_conflict(client: TestClient) -> None:
    _problem(client.post(f"{API}/sites", json={**SITE, "slug": "Bad Slug!"}, headers=INGEST), 422)
    _problem(client.post(f"{API}/sites", json={**SITE, "lat": 123}, headers=INGEST), 422)
    _create_site(client)
    _problem(client.post(f"{API}/sites", json=SITE, headers=INGEST), 409)


# ---------------------------------------------------------------- ingest → process → search
def test_upload_is_processed_linked_and_searchable(client: TestClient) -> None:
    site = _create_site(client)
    first = _upload(client, "field-notes.txt", JOURNAL.encode(), "text/plain", contributor="Fellow 1998")
    assert first["created"] is True and first["job_ids"]
    again = _upload(client, "copy.txt", JOURNAL.encode(), "text/plain")
    assert again["created"] is False and again["asset"]["id"] == first["asset"]["id"]  # content-addressed dedupe

    asset_id = first["asset"]["id"]
    asset = wait_for_asset(client, asset_id)
    assert asset["status"] == "ready" and asset["kind"] == "journal"
    assert asset["site_slug"] == "rani-ki-vav" and asset["era_year"] == 1998
    assert {e["kind"] for e in asset["entities"]} >= {"site", "date"}

    chunks = client.get(f"{API}/assets/{asset_id}/chunks").json()
    assert chunks and "excavations" in " ".join(c["text"] for c in chunks)
    original = client.get(f"{API}/assets/{asset_id}/original")
    assert original.status_code == 200 and original.content == JOURNAL.encode()

    res = client.get(f"{API}/search", params={"q": "sculpted panels"}).json()
    hit = res["hits"][0]
    assert hit["asset"]["id"] == asset_id and "keyword" in hit["matched_by"]
    marked = {hit["snippet"]["text"][a:b].lower() for a, b in hit["snippet"]["highlights"]}
    assert {"sculpted", "panels"} <= marked

    res = client.get(f"{API}/search", params={"q": "रानी की वाव"}).json()  # Devanagari query, Latin text
    assert any(h["asset"]["id"] == asset_id for h in res["hits"])
    assert res["sites"] and res["sites"][0]["slug"] == "rani-ki-vav"

    assert client.get(f"{API}/search", params={"q": "sculpted", "kind": "photo"}).json()["hits"] == []
    detail = client.get(f"{API}/sites/{site['slug']}").json()
    assert [a["id"] for a in detail["assets"]] == [asset_id]
    stats = client.get(f"{API}/stats").json()
    assert stats["assets"] == 1 and stats["chunks"] >= 1 and stats["sites"] == 1


def test_unsupported_upload_is_rejected(client: TestClient) -> None:
    r = client.post(
        f"{API}/assets",
        files=[("files", ("tool.exe", b"MZ\x90\x00binary", "application/octet-stream"))],
        headers=INGEST,
    )
    _problem(r, 415)


# ---------------------------------------------------------------- remote GPU worker protocol
def test_worker_endpoints_require_the_worker_token(client: TestClient) -> None:
    _problem(client.post(f"{API}/workers/register", json={"name": "x"}), 401)
    _problem(client.post(f"{API}/workers/register", json={"name": "x"}, headers=INGEST), 401)
    _problem(client.get(f"{API}/workers/blobs/originals/ab/abc.jpg"), 401)
    _problem(client.post(f"{API}/workers/not-registered/lease", json={}, headers=WORKER), 404)
    assert [w["queue"] for w in client.get(f"{API}/workers").json()] == ["cpu"]  # public dashboard listing


def test_gpu_caption_round_trip_makes_photo_searchable(client: TestClient) -> None:
    _create_site(client)
    site_id = client.get(f"{API}/sites/rani-ki-vav").json()["id"]
    photo = _upload(client, "panel.jpg", _jpeg(1), "image/jpeg", site_id=site_id)["asset"]
    assert wait_for_asset(client, photo["id"])["status"] == "ready"

    queued = client.get(f"{API}/jobs", params={"queue": "gpu", "status": "queued"}).json()
    assert [(j["type"], j["asset_title"]) for j in queued["items"]] == [("caption", photo["title"])]

    worker_id = _register(client, "caption")
    assert client.get(f"{API}/ready").json()["workers_online"] == {"cpu": 1, "gpu": 1}
    [job] = _lease(client, worker_id)
    assert job["type"] == "caption" and job["payload"]["asset_id"] == photo["id"]
    assert _lease(client, worker_id) == []  # leased jobs are never handed out twice

    assert job["payload"]["image_key"].startswith("thumbs/")  # GPUs get the small derivative, not the original
    blob = client.get(f"{API}/workers/blobs/{job['payload']['image_key']}", headers=WORKER)
    assert blob.status_code == 200
    assert Image.open(io.BytesIO(blob.content)).size[0] > 0

    hb = client.post(f"{API}/workers/{worker_id}/jobs/{job['id']}/heartbeat", headers=WORKER)
    assert hb.status_code == 200 and hb.json()["status"] == "leased"

    caption = "Carved stone apsara holding a mirror on a stepwell wall"
    r = client.post(
        f"{API}/workers/{worker_id}/jobs/{job['id']}/complete",
        json={"result": {"engine": "blip-large", "caption": caption}},
        headers=WORKER,
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "succeeded" and r.json()["result"]

    _problem(  # settling twice is a lease violation, not a silent overwrite
        client.post(
            f"{API}/workers/{worker_id}/jobs/{job['id']}/complete",
            json={"result": {"engine": "blip-large", "caption": "again"}},
            headers=WORKER,
        ),
        409,
    )

    asset = wait_for_asset(client, photo["id"])
    assert asset["caption"] == caption and asset["caption_source"] == "blip-large"
    hits: list[dict[str, Any]] = []
    for _ in range(100):  # the caption triggers a CPU re-index
        hits = client.get(f"{API}/search", params={"q": "apsara mirror"}).json()["hits"]
        if hits:
            break
        time.sleep(0.1)
    assert hits and hits[0]["asset"]["id"] == photo["id"]

    [w] = [w for w in client.get(f"{API}/workers").json() if w["queue"] == "gpu"]
    assert w["id"] == worker_id and w["jobs_done"] == 1


def test_invalid_gpu_results_are_dead_lettered_and_failures_retried(client: TestClient) -> None:
    for seed in (2, 3):
        wait_for_asset(client, _upload(client, f"p{seed}.jpg", _jpeg(seed), "image/jpeg")["asset"]["id"])
    worker_id = _register(client, "caption")
    first, second = _lease(client, worker_id, limit=2)

    r = client.post(
        f"{API}/workers/{worker_id}/jobs/{first['id']}/complete",
        json={"result": {"engine": "blip", "caption": ""}},  # violates CaptionResult
        headers=WORKER,
    )
    _problem(r, 422)
    dead = client.get(f"{API}/jobs/{first['id']}").json()
    assert dead["status"] == "dead" and dead["lease_owner"] is None

    r = client.post(
        f"{API}/workers/{worker_id}/jobs/{second['id']}/fail",
        json={"error": "CUDA out of memory", "retryable": True},
        headers=WORKER,
    )
    assert r.status_code == 200 and r.json()["status"] == "failed" and r.json()["error"] == "CUDA out of memory"
    assert _lease(client, worker_id) == []  # exponential backoff before the retry

    retried = client.post(f"{API}/jobs/{first['id']}/retry", headers=INGEST)
    assert retried.status_code == 200 and retried.json()["status"] == "queued"
    [again] = _lease(client, worker_id)
    assert again["id"] == first["id"]

    [w] = [w for w in client.get(f"{API}/workers").json() if w["queue"] == "gpu"]
    assert w["jobs_failed"] == 2


def test_blob_access_is_limited_to_job_inputs(client: TestClient) -> None:
    for key in ("twins/site-1/x.ply", "originals/../secrets.txt", "derived/1.json"):
        _problem(client.get(f"{API}/workers/blobs/{key}", headers=WORKER), 404)


def test_reconstruction_artifact_upload_creates_a_digital_twin(client: TestClient) -> None:
    site = _create_site(client)
    photos = [
        _upload(client, f"vav-{i}.jpg", _jpeg(10 + i), "image/jpeg", site_id=site["id"], caption=f"Pavilion {i}")
        for i in range(2)
    ]
    ids = [wait_for_asset(client, p["asset"]["id"])["id"] for p in photos]

    _problem(client.post(f"{API}/sites/rani-ki-vav/twins", json={"asset_ids": ids}), 401)
    _problem(
        client.post(
            f"{API}/sites/rani-ki-vav/twins", json={"asset_ids": ids, "method": "gaussian-splat"}, headers=INGEST
        ),
        422,
    )
    r = client.post(f"{API}/sites/rani-ki-vav/twins", json={"asset_ids": ids, "title": "Relief study"}, headers=INGEST)
    assert r.status_code == 202 and r.json()["type"] == "reconstruct3d" and r.json()["queue"] == "gpu"
    listed = client.get(f"{API}/jobs/{r.json()['id']}").json()
    assert (listed["site_name"], listed["site_slug"], listed["asset_title"]) == (site["name"], "rani-ki-vav", None)

    worker_id = _register(client, "reconstruct3d")
    [job] = _lease(client, worker_id)
    assert {i["asset_id"] for i in job["payload"]["images"]} == set(ids)
    first_key = job["payload"]["images"][0]["image_key"]
    assert first_key.startswith("originals/")  # depth estimation needs full resolution
    blob = client.get(f"{API}/workers/blobs/{first_key}", headers=WORKER)
    assert blob.status_code == 200 and blob.content in {_jpeg(10), _jpeg(11)}

    upload = f"{API}/workers/{worker_id}/jobs/{job['id']}/artifacts"
    _problem(client.post(upload, files={"file": ("model.obj", b"v 0 0 0", "text/plain")}, headers=WORKER), 415)
    _problem(client.post(upload, files={"file": ("model.ply", b"not a ply", "text/plain")}, headers=WORKER), 415)

    ply = write_ply(vav_stepwell(pavilions=2, density=200))
    r = client.post(upload, files={"file": ("relief.ply", ply, "application/octet-stream")}, headers=WORKER)
    assert r.status_code == 200, r.text
    artifact = r.json()
    assert artifact["key"].startswith(f"twins/site-{site['id']}/job-{job['id']}/") and artifact["format"] == "ply"
    assert artifact["point_count"] and artifact["size_bytes"] == len(ply)

    result = {
        "artifact_key": artifact["key"],
        "format": "ply",
        "method": "depth-relief",
        "point_count": artifact["point_count"],
        "source_asset_ids": ids,
    }
    r = client.post(f"{API}/workers/{worker_id}/jobs/{job['id']}/complete", json={"result": result}, headers=WORKER)
    assert r.status_code == 200 and r.json()["status"] == "succeeded", r.text

    [twin] = client.get(f"{API}/sites/rani-ki-vav/twins").json()
    assert twin["title"] == "Relief study" and twin["point_count"] == artifact["point_count"]
    model = client.get(f"{API}/twins/{twin['id']}/file")
    assert model.status_code == 200 and model.content == ply

    _problem(client.post(upload, files={"file": ("late.ply", ply, "application/octet-stream")}, headers=WORKER), 409)
