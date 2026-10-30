"""Pull-based worker protocol.

Remote GPU workers (e.g. a Colab notebook behind NAT) never need an inbound connection: they
register, lease jobs, heartbeat, fetch inputs by storage key, upload artifacts and report results -
all over outbound HTTPS with a bearer token. Results are schema-validated before they touch the DB.
"""

from __future__ import annotations

import re
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Request, Response, UploadFile
from sqlalchemy import select

from app.api.deps import ServicesDep, SessionDep
from app.api.files import blob_response
from app.core.errors import AppError, NotFoundError, PayloadTooLargeError
from app.core.security import require_worker
from app.db.base import utcnow
from app.db.models import Job, JobStatus, Worker
from app.schemas.catalog import JobOut
from app.schemas.worker import (
    ArtifactOut,
    CompleteRequest,
    FailRequest,
    LeasedJob,
    LeaseRequest,
    LeaseResponse,
    WorkerOut,
    WorkerRegister,
)
from app.services import twins as twin_files
from app.services.jobs import LeaseLostError
from app.services.pipeline import fail_job, settle_job

router = APIRouter(prefix="/workers", tags=["workers"])
protected = APIRouter(prefix="/workers", tags=["workers"], dependencies=[Depends(require_worker)])

BLOB_PREFIXES = ("originals/", "pages/", "thumbs/")
MAX_ARTIFACT_MB = 512
_SAFE = re.compile(r"[^a-z0-9]+")


def worker_out(w: Worker, offline_after: int) -> WorkerOut:
    out = WorkerOut.model_validate(w)
    out.online = (utcnow() - w.last_seen_at).total_seconds() <= offline_after
    return out


async def _worker(session: SessionDep, worker_id: str) -> Worker:
    w = await session.get(Worker, worker_id)
    if w is None:
        raise NotFoundError(f"worker {worker_id} is not registered")
    w.last_seen_at = utcnow()
    return w


@router.get("", response_model=list[WorkerOut], summary="Connected workers (CPU + GPU)")
async def list_workers(services: ServicesDep, session: SessionDep) -> list[WorkerOut]:
    rows = (await session.scalars(select(Worker).order_by(Worker.last_seen_at.desc()).limit(100))).all()
    return [worker_out(w, services.settings.worker_offline_after_seconds) for w in rows]


@protected.post("/register", response_model=WorkerOut)
async def register(services: ServicesDep, session: SessionDep, body: WorkerRegister) -> WorkerOut:
    slug = _SAFE.sub("-", body.name.lower()).strip("-")[:24] or "worker"
    w = Worker(
        id=f"{body.queue}-{slug}-{uuid.uuid4().hex[:8]}",
        name=body.name,
        queue=body.queue,
        device=body.device,
        capabilities=body.capabilities,
    )
    session.add(w)
    await session.commit()
    return worker_out(w, services.settings.worker_offline_after_seconds)


@protected.post("/{worker_id}/lease", response_model=LeaseResponse)
async def lease(services: ServicesDep, session: SessionDep, worker_id: str, body: LeaseRequest) -> LeaseResponse:
    w = await _worker(session, worker_id)
    types = body.types or w.capabilities or None
    jobs = await services.queue.lease(
        session, worker_id, w.queue, types=types, limit=body.limit, lease_seconds=body.lease_seconds
    )
    return LeaseResponse(jobs=[LeasedJob.model_validate(j) for j in jobs])


@protected.post("/{worker_id}/jobs/{job_id}/heartbeat", response_model=JobOut)
async def heartbeat(services: ServicesDep, session: SessionDep, worker_id: str, job_id: int) -> JobOut:
    await _worker(session, worker_id)
    return JobOut.model_validate(await services.queue.heartbeat(session, job_id, worker_id))


@protected.post("/{worker_id}/jobs/{job_id}/complete", response_model=JobOut)
async def complete(
    services: ServicesDep, session: SessionDep, worker_id: str, job_id: int, body: CompleteRequest
) -> JobOut:
    await _worker(session, worker_id)
    job = await settle_job(services.ctx, session, job_id, worker_id, body.result)
    return JobOut.model_validate(job)


@protected.post("/{worker_id}/jobs/{job_id}/fail", response_model=JobOut)
async def fail(services: ServicesDep, session: SessionDep, worker_id: str, job_id: int, body: FailRequest) -> JobOut:
    await _worker(session, worker_id)
    job = await fail_job(services.ctx, session, job_id, worker_id, body.error, retryable=body.retryable)
    return JobOut.model_validate(job)


@protected.post(
    "/{worker_id}/jobs/{job_id}/artifacts",
    response_model=ArtifactOut,
    summary="Upload a 3D artifact (.ply / .splat / .glb) produced by a leased job",
)
async def upload_artifact(
    services: ServicesDep,
    session: SessionDep,
    worker_id: str,
    job_id: int,
    file: Annotated[UploadFile, File()],
) -> ArtifactOut:
    await _worker(session, worker_id)
    job = await session.get(Job, job_id)
    if job is None or job.status != JobStatus.leased or job.lease_owner != worker_id:
        raise LeaseLostError(f"job {job_id} is not leased by {worker_id}")
    if job.type != "reconstruct3d" or job.site_id is None:
        raise AppError("only reconstruct3d jobs can upload artifacts")
    data = await file.read(MAX_ARTIFACT_MB * 1024 * 1024 + 1)
    if len(data) > MAX_ARTIFACT_MB * 1024 * 1024:
        raise PayloadTooLargeError(f"artifact exceeds {MAX_ARTIFACT_MB} MB")
    name = (file.filename or "artifact").lower()
    ext = name.rsplit(".", 1)[-1] if "." in name else ""
    try:
        if ext == "ply":
            points: int | None = int(twin_files.read_ply_header(data)["vertex_count"])  # type: ignore[call-overload]
        elif ext == "splat":
            points = twin_files.splat_vertex_count(data)
        elif ext == "glb":
            if not twin_files.glb_is_valid(data):
                raise ValueError("not a glTF 2.0 binary")
            points = None
        else:
            raise ValueError("artifact must be .ply, .splat or .glb")
    except ValueError as exc:
        raise AppError(str(exc), status_code=415, title="Unsupported artifact") from exc
    key = f"twins/site-{job.site_id}/job-{job.id}/{uuid.uuid4().hex[:8]}.{ext}"
    await services.storage.put(key, data)
    await session.commit()
    return ArtifactOut(key=key, size_bytes=len(data), format=ext, point_count=points)


@protected.get("/blobs/{key:path}", response_class=Response, summary="Fetch a job input by storage key")
async def blob(request: Request, services: ServicesDep, key: str) -> Response:
    if not key.startswith(BLOB_PREFIXES) or ".." in key:
        raise NotFoundError("blob not available to workers")
    try:
        return await blob_response(request, services.storage, key)
    except ValueError as exc:
        raise NotFoundError("invalid key") from exc
