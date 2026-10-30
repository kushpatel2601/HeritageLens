"""Handler contract and job settlement shared by local workers and the remote-worker API.

Every job type has one `Handler`:

* ``run``   - computes the result. Present for CPU job types (and GPU types with a CPU fallback).
              Remote GPU workers implement the equivalent in ``ml/heritage_gpu``.
* ``apply`` - persists a (validated) result into domain tables. Runs in the same transaction that
              marks the job succeeded, so domain state and job state never diverge.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, ClassVar

from pydantic import BaseModel, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError
from app.db.models import Asset, AssetStatus, Job, JobStatus
from app.db.session import Database
from app.services.jobs import JobQueue
from app.services.storage import Storage

log = logging.getLogger(__name__)


@dataclass(slots=True)
class JobContext:
    settings: Settings
    db: Database
    storage: Storage
    queue: JobQueue


class InvalidResultError(AppError):
    status_code = 422
    title = "Invalid job result"


# Module-level alias: inside `Handler` the name `type` is shadowed by the job-type ClassVar.
ResultModel = type[BaseModel]


class Handler:
    type: ClassVar[str]
    blocking: ClassVar[bool] = True  # a dead job marks its asset as failed
    result_model: ClassVar[ResultModel | None] = None

    def runs_locally(self, ctx: JobContext) -> bool:
        return True

    async def run(self, ctx: JobContext, job: Job) -> dict[str, Any]:
        raise NotImplementedError(f"job type {self.type!r} has no local implementation")

    async def apply(self, ctx: JobContext, session: AsyncSession, job: Job, result: dict[str, Any]) -> None:
        return None

    def validate(self, result: dict[str, Any]) -> dict[str, Any]:
        if self.result_model is None:
            return result
        try:
            return self.result_model.model_validate(result).model_dump()
        except ValidationError as exc:
            raise InvalidResultError(f"{self.type} result rejected: {exc.errors(include_url=False)}") from exc

    def summarize(self, result: dict[str, Any]) -> dict[str, Any]:
        """What to keep on the job row (large payloads already live in domain tables)."""
        return result

    async def on_dead(self, ctx: JobContext, session: AsyncSession, job: Job) -> None:
        if self.blocking and job.asset_id is not None:
            asset = await session.get(Asset, job.asset_id)
            if asset is not None:
                asset.status = AssetStatus.failed
                asset.error = f"{self.type}: {job.error}"


HANDLERS: dict[str, Handler] = {}


def register(cls: type[Handler]) -> type[Handler]:
    HANDLERS[cls.type] = cls()
    return cls


def get_handler(job_type: str) -> Handler:
    try:
        return HANDLERS[job_type]
    except KeyError:
        raise AppError(f"unknown job type {job_type!r}") from None


async def enqueue_index(ctx: JobContext, session: AsyncSession, asset_id: int, priority: int = 100) -> Job:
    return await ctx.queue.enqueue(
        session,
        "index",
        {"asset_id": asset_id},
        asset_id=asset_id,
        priority=priority,
        dedupe_key=f"index:{asset_id}",
    )


async def fail_job(
    ctx: JobContext, session: AsyncSession, job_id: int, worker_id: str, error: str, *, retryable: bool = True
) -> Job:
    job = await ctx.queue.fail(session, job_id, worker_id, error, retryable=retryable)
    if job.status == JobStatus.dead:
        await get_handler(job.type).on_dead(ctx, session, job)
    await session.commit()
    return job


async def settle_job(
    ctx: JobContext, session: AsyncSession, job_id: int, worker_id: str, result: dict[str, Any]
) -> Job:
    """Validate + apply a result atomically with marking the job succeeded.

    Invalid results are dead-lettered (deterministic); errors while applying are retried.
    Lease-ownership errors propagate unchanged.
    """
    job = await ctx.queue.complete(session, job_id, worker_id, None)
    handler = get_handler(job.type)
    try:
        clean = handler.validate(result)
        await handler.apply(ctx, session, job, clean)
        job.result = handler.summarize(clean)
        await session.commit()
        return job
    except InvalidResultError as exc:
        await session.rollback()
        await fail_job(ctx, session, job_id, worker_id, exc.detail, retryable=False)
        raise
    except Exception as exc:
        await session.rollback()
        log.exception("applying %s result for job %s failed", job.type, job_id)
        return await fail_job(ctx, session, job_id, worker_id, f"apply failed: {exc!r}")


async def reap(ctx: JobContext) -> int:
    async with ctx.db.sessionmaker() as session:
        jobs = await ctx.queue.reap_expired(session)
        for job in jobs:
            if job.status == JobStatus.dead:
                await get_handler(job.type).on_dead(ctx, session, job)
        await session.commit()
        return len(jobs)
