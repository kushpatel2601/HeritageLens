from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest
from fakeserver import BASE, TOKEN, FakeServer

from heritage_gpu import __version__
from heritage_gpu.client import ApiClient, LeasedJob
from heritage_gpu.errors import ApiError, InvalidResultError, LeaseLostError, NotRegisteredError

Handler = Callable[[httpx.Request], httpx.Response]


def make_client(handler: Handler, *, retries: int = 2, token: str = TOKEN) -> tuple[ApiClient, list[float]]:
    sleeps: list[float] = []
    http = httpx.Client(transport=httpx.MockTransport(handler))
    return ApiClient(BASE, token, http=http, retries=retries, backoff=0.5, sleep=sleeps.append), sleeps


def scripted(*responses: httpx.Response | Exception) -> tuple[Handler, list[httpx.Request]]:
    seen: list[httpx.Request] = []
    queue = list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(item, Exception):
            raise item
        return item

    return handler, seen


def test_requests_carry_credentials_and_version() -> None:
    server = FakeServer()
    client, _ = make_client(server.handle)
    worker_id = client.register("colab", ["ocr", "caption"], "Tesla T4")
    assert worker_id == "gpu-test-1" and server.workers[worker_id] == ["ocr", "caption"]

    handler, seen = scripted(httpx.Response(200, json={"jobs": []}))
    client, _ = make_client(handler)
    assert client.lease("w", ["ocr"], limit=2, lease_seconds=120) == []
    request = seen[0]
    assert request.headers["authorization"] == f"Bearer {TOKEN}"
    assert request.headers["user-agent"] == f"heritage-gpu/{__version__}"
    assert str(request.url) == f"{BASE}/workers/w/lease"
    assert json.loads(request.content) == {"types": ["ocr"], "limit": 2, "lease_seconds": 120}


def test_gateway_errors_are_retried_with_exponential_backoff() -> None:
    handler, seen = scripted(
        httpx.Response(502), httpx.Response(503), httpx.Response(200, json={"id": "gpu-x", "online": True})
    )
    client, sleeps = make_client(handler)
    assert client.register("w", ["ocr"], None) == "gpu-x"
    assert len(seen) == 3
    assert 0.25 <= sleeps[0] <= 0.75 and 0.5 <= sleeps[1] <= 1.5  # backoff * 2**attempt * jitter(0.5..1.5)


def test_retries_are_bounded() -> None:
    handler, seen = scripted(httpx.Response(504, text="gateway timeout"))
    client, sleeps = make_client(handler, retries=2)
    with pytest.raises(ApiError) as err:
        client.register("w", ["ocr"], None)
    assert err.value.status == 504 and err.value.detail == "gateway timeout"
    assert len(seen) == 3 and len(sleeps) == 2


def test_transport_errors_are_retried_then_raised() -> None:
    handler, seen = scripted(httpx.ConnectError("tunnel asleep"))
    client, _ = make_client(handler, retries=1)
    with pytest.raises(httpx.ConnectError):
        client.heartbeat("w", 1)
    assert len(seen) == 2

    handler, seen = scripted(httpx.ReadTimeout("slow"), httpx.Response(200, json={"status": "leased"}))
    client, _ = make_client(handler, retries=1)
    client.heartbeat("w", 1)
    assert len(seen) == 2


def test_client_errors_are_not_retried() -> None:
    handler, seen = scripted(httpx.Response(400, json={"detail": "bad limit"}))
    client, sleeps = make_client(handler)
    with pytest.raises(ApiError, match="bad limit") as err:
        client.lease("w", ["ocr"], limit=99)
    assert err.value.status == 400 and type(err.value) is ApiError
    assert len(seen) == 1 and sleeps == []


@pytest.mark.parametrize(
    ("call", "status", "expected"),
    [
        (lambda c: c.heartbeat("w", 1), 409, LeaseLostError),
        (lambda c: c.complete("w", 1, {}), 409, LeaseLostError),
        (lambda c: c.complete("w", 1, {}), 422, InvalidResultError),
        (lambda c: c.lease("w", ["ocr"]), 404, NotRegisteredError),
        (lambda c: c.blob("pages/1/1.png"), 404, ApiError),  # not worker-scoped: plain 404
        (lambda c: c.register("w", [], None), 401, ApiError),
    ],
)
def test_status_codes_map_to_typed_errors(
    call: Callable[[ApiClient], object], status: int, expected: type[ApiError]
) -> None:
    handler, _ = scripted(httpx.Response(status, json={"title": "Conflict", "detail": "explained"}))
    client, _ = make_client(handler)
    with pytest.raises(ApiError) as err:
        call(client)
    assert type(err.value) is expected and err.value.status == status and err.value.detail == "explained"


def test_token_check_is_side_effect_free() -> None:
    server = FakeServer()
    good, _ = make_client(server.handle)
    bad, _ = make_client(server.handle, token="wrong")
    assert good.token_is_valid() is True and bad.token_is_valid() is False
    assert server.registrations == 0 and all("lease" in r for r in server.requests)


def test_health_returns_degraded_bodies_instead_of_raising() -> None:
    degraded = {"status": "degraded", "checks": {"storage": "error: OSError"}}
    handler, _ = scripted(httpx.Response(503, json=degraded))
    client, _ = make_client(handler, retries=0)
    assert client.health() == degraded

    handler, _ = scripted(httpx.Response(503, text="<html>tunnel down</html>"))
    client, _ = make_client(handler, retries=0)
    with pytest.raises(ApiError) as err:
        client.health()
    assert err.value.status == 503


def test_fail_truncates_long_errors_and_artifacts_upload_as_multipart() -> None:
    server = FakeServer()
    client, _ = make_client(server.handle)
    worker_id = client.register("w", ["reconstruct3d"], None)
    job = server.add("reconstruct3d", {"images": []})
    [leased] = client.lease(worker_id, ["reconstruct3d"])
    assert leased == LeasedJob(id=job.id, type="reconstruct3d", payload={"images": []}, attempts=1)

    artifact = client.upload_artifact(worker_id, job.id, "relief.ply", b"ply\n...")
    assert server.artifacts[artifact["key"]] == b"ply\n..."
    client.fail(worker_id, job.id, "x" * 10_000, retryable=False)
    assert job.error == "x" * 3900 and job.retryable is False


def test_only_owned_http_clients_are_closed() -> None:
    http = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200)))
    with ApiClient(BASE, TOKEN, http=http):
        pass
    assert not http.is_closed
    with ApiClient(BASE, TOKEN) as owned:
        inner = owned._http
    assert inner.is_closed
