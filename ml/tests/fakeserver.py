"""An in-memory implementation of the server side of the worker protocol, served through
``httpx.MockTransport``. It mirrors the status codes of ``backend/app/api/routes/workers.py``
closely enough to drive the client and runner through every branch without a network."""

from __future__ import annotations

import itertools
import json
import threading
from dataclasses import dataclass, field
from typing import Any

import httpx

TOKEN = "unit-test-token"
BASE = "http://hl.test/api/v1"


@dataclass
class ServerJob:
    id: int
    type: str
    payload: dict[str, Any]
    attempts: int = 0
    status: str = "queued"
    owner: str | None = None
    result: dict[str, Any] | None = None
    error: str | None = None
    retryable: bool | None = None


@dataclass
class FakeServer:
    blobs: dict[str, bytes] = field(default_factory=dict)
    jobs: dict[int, ServerJob] = field(default_factory=dict)
    workers: dict[str, list[str]] = field(default_factory=dict)
    artifacts: dict[str, bytes] = field(default_factory=dict)
    registrations: int = 0
    heartbeats: int = 0
    requests: list[str] = field(default_factory=list)
    # Fault injection
    forget_workers_once: bool = False
    lose_lease_on_heartbeat: set[int] = field(default_factory=set)
    lose_lease_on_complete: set[int] = field(default_factory=set)
    reject_results: set[int] = field(default_factory=set)
    _ids: itertools.count[int] = field(default_factory=lambda: itertools.count(1))
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def add(self, job_type: str, payload: dict[str, Any]) -> ServerJob:
        job = ServerJob(next(self._ids), job_type, payload)
        self.jobs[job.id] = job
        return job

    def http(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handle))

    # ------------------------------------------------------------------ routing
    def handle(self, request: httpx.Request) -> httpx.Response:
        with self._lock:
            path = request.url.path.removeprefix("/api/v1")
            self.requests.append(f"{request.method} {path}")
            if request.headers.get("authorization") != f"Bearer {TOKEN}":
                return _problem(401, "invalid worker token")
            parts = path.strip("/").split("/")
            body = json.loads(request.content) if request.headers.get("content-type") == "application/json" else {}
            if parts == ["workers", "register"]:
                return self._register(body)
            if parts[:2] == ["workers", "blobs"]:
                key = "/".join(parts[2:])
                return httpx.Response(200, content=self.blobs[key]) if key in self.blobs else _problem(404, key)
            if len(parts) == 3 and parts[2] == "lease":
                return self._lease(parts[1], body)
            if len(parts) == 5 and parts[2] == "jobs":
                return self._job_call(parts[1], int(parts[3]), parts[4], request, body)
            return _problem(404, f"no route {path}")

    def _register(self, body: dict[str, Any]) -> httpx.Response:
        self.registrations += 1
        worker_id = f"gpu-test-{self.registrations}"
        self.workers[worker_id] = list(body["capabilities"])
        return httpx.Response(200, json={"id": worker_id, "online": True})

    def _lease(self, worker_id: str, body: dict[str, Any]) -> httpx.Response:
        if self.forget_workers_once:
            self.forget_workers_once = False
            self.workers.clear()
        if worker_id not in self.workers:
            return _problem(404, f"worker {worker_id} not registered")
        types = body.get("types") or self.workers[worker_id]
        leased = []
        for job in self.jobs.values():
            if len(leased) >= body.get("limit", 1):
                break
            if job.status == "queued" and job.type in types:
                job.status, job.owner, job.attempts = "leased", worker_id, job.attempts + 1
                leased.append({"id": job.id, "type": job.type, "payload": job.payload, "attempts": job.attempts})
        return httpx.Response(200, json={"jobs": leased})

    def _job_call(
        self, worker_id: str, job_id: int, action: str, request: httpx.Request, body: dict[str, Any]
    ) -> httpx.Response:
        if worker_id not in self.workers:
            return _problem(404, f"worker {worker_id} not registered")
        job = self.jobs.get(job_id)
        if job is None:
            return _problem(404, f"job {job_id} not found")
        if job.owner != worker_id or job.status != "leased":
            return _problem(409, "lease lost")
        if action == "heartbeat":
            self.heartbeats += 1
            if job_id in self.lose_lease_on_heartbeat:
                job.status, job.owner = "queued", None
                return _problem(409, "lease expired")
            return httpx.Response(200, json={"id": job_id, "status": "leased"})
        if action == "artifacts":
            ext = _filename(request).rsplit(".", 1)[-1]
            if ext not in ("ply", "splat", "glb"):
                return _problem(415, f"unsupported artifact .{ext}")
            key = f"twins/site-1/job-{job_id}/{len(self.artifacts):04x}.{ext}"
            self.artifacts[key] = _file_bytes(request)
            return httpx.Response(200, json={"key": key, "size_bytes": len(self.artifacts[key]), "format": ext})
        if action == "complete":
            if job_id in self.lose_lease_on_complete:
                job.owner = "gpu-other-worker"  # the lease expired and another worker picked the job up
                return _problem(409, "lease expired")
            if job_id in self.reject_results:
                job.status = "dead"
                return _problem(422, "result failed validation")
            job.status, job.result = "succeeded", body["result"]
            return httpx.Response(200, json={"id": job_id, "status": "succeeded"})
        if action == "fail":
            job.status, job.error, job.retryable = "failed", body["error"], body["retryable"]
            return httpx.Response(200, json={"id": job_id, "status": "failed"})
        return _problem(404, action)


def _problem(status: int, detail: str) -> httpx.Response:
    return httpx.Response(
        status,
        json={"type": "about:blank", "title": "error", "status": status, "detail": detail},
        headers={"content-type": "application/problem+json"},
    )


def _multipart_part(request: httpx.Request) -> bytes:
    content_type = request.headers["content-type"]
    boundary = content_type.split("boundary=", 1)[1].encode()
    [part] = [p for p in request.content.split(b"--" + boundary) if b'name="file"' in p]
    return part


def _filename(request: httpx.Request) -> str:
    head = _multipart_part(request).split(b"\r\n\r\n", 1)[0].decode()
    return head.split('filename="', 1)[1].split('"', 1)[0]


def _file_bytes(request: httpx.Request) -> bytes:
    return _multipart_part(request).split(b"\r\n\r\n", 1)[1].removesuffix(b"\r\n")
