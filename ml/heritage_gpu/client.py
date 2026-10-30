"""Typed, retrying client for the HeritageLens worker protocol (``/api/v1/workers/...``).

Only transport errors and 502/503/504 (typical of tunnels such as cloudflared / ngrok waking up)
are retried, with exponential backoff and jitter. 4xx answers are protocol decisions and surface
as typed exceptions so the runner can react (re-register, drop a lost lease, ...).
"""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx

from heritage_gpu import __version__
from heritage_gpu.errors import ApiError, InvalidResultError, LeaseLostError, NotRegisteredError

log = logging.getLogger(__name__)

RETRY_STATUS = frozenset({502, 503, 504})


@dataclass(frozen=True, slots=True)
class LeasedJob:
    id: int
    type: str
    payload: dict[str, Any]
    attempts: int

    @classmethod
    def parse(cls, raw: dict[str, Any]) -> LeasedJob:
        return cls(
            id=int(raw["id"]), type=str(raw["type"]), payload=dict(raw["payload"]), attempts=int(raw["attempts"])
        )


class ApiClient:
    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        http: httpx.Client | None = None,
        timeout: float = 120.0,
        retries: int = 4,
        backoff: float = 1.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {token}", "User-Agent": f"heritage-gpu/{__version__}"}
        self._owns_http = http is None
        self._http = http or httpx.Client(timeout=httpx.Timeout(timeout, connect=15.0), follow_redirects=True)
        self._retries = retries
        self._backoff = backoff
        self._sleep = sleep

    # ------------------------------------------------------------------ transport
    def _request(self, method: str, path: str, **kw: Any) -> httpx.Response:
        url = f"{self.base_url}{path}"
        attempt = 0
        while True:
            try:
                r = self._http.request(method, url, headers=self._headers, **kw)
            except httpx.TransportError as exc:
                if attempt >= self._retries:
                    raise
                log.warning("%s %s failed (%s); retrying", method, path, exc.__class__.__name__)
            else:
                if r.status_code not in RETRY_STATUS or attempt >= self._retries:
                    return r
                log.warning("%s %s -> %s; retrying", method, path, r.status_code)
            self._sleep(self._backoff * (2**attempt) * (0.5 + random.random()))
            attempt += 1

    @staticmethod
    def _raise_for(r: httpx.Response, *, worker_scoped: bool = False) -> None:
        if r.is_success:
            return
        try:
            body = r.json()
            detail = str(body.get("detail") or body.get("title") or r.text)
        except ValueError:
            detail = r.text[:500]
        if r.status_code == 409:
            raise LeaseLostError(409, detail)
        if r.status_code == 422:
            raise InvalidResultError(422, detail)
        if r.status_code == 404 and worker_scoped:
            raise NotRegisteredError(404, detail)
        raise ApiError(r.status_code, detail)

    def _json(self, method: str, path: str, *, worker_scoped: bool = False, **kw: Any) -> Any:
        r = self._request(method, path, **kw)
        self._raise_for(r, worker_scoped=worker_scoped)
        return r.json()

    # ------------------------------------------------------------------ diagnostics
    def health(self) -> dict[str, Any]:
        """Public readiness probe (DB, storage, connected workers); 503 bodies are returned too."""
        r = self._request("GET", "/ready")
        try:
            return dict(r.json())
        except ValueError:
            self._raise_for(r)
            raise

    def stats(self) -> dict[str, Any]:
        return dict(self._json("GET", "/stats"))

    def token_is_valid(self) -> bool:
        """Leasing for a worker id that cannot exist answers 404 when the token is accepted and 401
        when it is not - a side-effect-free credential check."""
        r = self._request("POST", "/workers/~token-check/lease", json={})
        if r.status_code in (401, 403):
            return False
        if r.status_code == 404:
            return True
        self._raise_for(r)
        return True

    # ------------------------------------------------------------------ protocol
    def register(self, name: str, capabilities: list[str], device: str | None) -> str:
        body = {"name": name, "queue": "gpu", "device": device, "capabilities": capabilities}
        return str(self._json("POST", "/workers/register", json=body)["id"])

    def lease(
        self, worker_id: str, types: list[str], *, limit: int = 1, lease_seconds: int | None = None
    ) -> list[LeasedJob]:
        body: dict[str, Any] = {"types": types, "limit": limit}
        if lease_seconds is not None:
            body["lease_seconds"] = lease_seconds
        data = self._json("POST", f"/workers/{worker_id}/lease", worker_scoped=True, json=body)
        return [LeasedJob.parse(j) for j in data["jobs"]]

    def heartbeat(self, worker_id: str, job_id: int) -> None:
        self._json("POST", f"/workers/{worker_id}/jobs/{job_id}/heartbeat")

    def complete(self, worker_id: str, job_id: int, result: dict[str, Any]) -> dict[str, Any]:
        return dict(self._json("POST", f"/workers/{worker_id}/jobs/{job_id}/complete", json={"result": result}))

    def fail(self, worker_id: str, job_id: int, error: str, *, retryable: bool) -> dict[str, Any]:
        body = {"error": error[:3900], "retryable": retryable}
        return dict(self._json("POST", f"/workers/{worker_id}/jobs/{job_id}/fail", json=body))

    def blob(self, key: str) -> bytes:
        r = self._request("GET", f"/workers/blobs/{key}")
        self._raise_for(r)
        return r.content

    def upload_artifact(self, worker_id: str, job_id: int, filename: str, data: bytes) -> dict[str, Any]:
        files = {"file": (filename, data, "application/octet-stream")}
        return dict(self._json("POST", f"/workers/{worker_id}/jobs/{job_id}/artifacts", files=files))

    def close(self) -> None:
        if self._owns_http:
            self._http.close()

    def __enter__(self) -> ApiClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
