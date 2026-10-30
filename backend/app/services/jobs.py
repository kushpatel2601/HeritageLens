from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import timedelta
from typing import Any

from sqlalchemy import Select, and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.errors import AppError, NotFoundError
from app.db.base import utcnow
from app.db.models import Asset, Job, JobStatus, Site, Worker

log = logging.getLogger(__name__)

ACTIVE = (JobStatus.queued, JobStatus.leased, JobStatus.failed)
LEASABLE = (JobStatus.queued, JobStatus.failed)


def labelled_jobs() -> Select[Job, str, str, str]:
    """Jobs with the names of what they work on (asset title, site name/slug; NULL when absent).

    One outer join instead of N lookups, so dashboards and live events can say *what* is being
    processed rather than a bare id.
    """
    return (
        select(Job, Asset.title, Site.name, Site.slug)
        .outerjoin(Asset, Asset.id == Job.asset_id)
        .outerjoin(Site, Site.id == Job.site_id)
    )


class LeaseLostError(AppError):
    status_code = 409
    title = "Lease lost"


def tesseract_available() -> bool:
    try:
        import pytesseract

        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


class JobQueue:
    """Durable work queue on the primary database.

    * PostgreSQL: `SELECT ... FOR UPDATE SKIP LOCKED` - many concurrent workers, zero contention.
    * SQLite: optimistic compare-and-set `UPDATE ... WHERE status IN (queued, failed)`.
    Both give at-least-once delivery; handlers are written to be idempotent.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._cpu_fallback: dict[str, bool] = {}

    # ------------------------------------------------------------------ routing
    def route(self, job_type: str) -> str:
        if job_type not in self.settings.gpu_jobs:
            return "cpu"
        if self.settings.gpu_fallback_to_cpu and self.has_cpu_impl(job_type):
            return "cpu"
        return "gpu"

    def has_cpu_impl(self, job_type: str) -> bool:
        if job_type not in self._cpu_fallback:
            self._cpu_fallback[job_type] = job_type == "ocr" and tesseract_available()
        return self._cpu_fallback[job_type]

    # ------------------------------------------------------------------ produce
    async def enqueue(
        self,
        session: AsyncSession,
        job_type: str,
        payload: dict[str, Any],
        *,
        asset_id: int | None = None,
        site_id: int | None = None,
        priority: int = 100,
        dedupe_key: str | None = None,
        queue: str | None = None,
    ) -> Job:
        if dedupe_key:
            # Debounce: coalesce with a job that has not started yet. If the matching job is already
            # running, enqueue a fresh one so the newest inputs are processed after it.
            existing = await session.scalar(
                select(Job).where(Job.dedupe_key == dedupe_key, Job.status.in_(LEASABLE)).limit(1)
            )
            if existing is not None:
                existing.payload = payload
                return existing
        job = Job(
            type=job_type,
            queue=queue or self.route(job_type),
            payload=payload,
            asset_id=asset_id,
            site_id=site_id,
            priority=priority,
            dedupe_key=dedupe_key,
            max_attempts=self.settings.job_max_attempts,
            status=JobStatus.queued,
            run_after=utcnow(),
        )
        session.add(job)
        await session.flush()
        log.info("enqueued %s #%s on %s", job_type, job.id, job.queue, extra={"job_id": job.id})
        return job

    # ------------------------------------------------------------------ consume
    async def lease(
        self,
        session: AsyncSession,
        worker_id: str,
        queue: str,
        *,
        types: Sequence[str] | None = None,
        limit: int = 1,
        lease_seconds: int | None = None,
    ) -> list[Job]:
        now = utcnow()
        expires = now + timedelta(seconds=lease_seconds or self.settings.job_lease_seconds)
        conds = [Job.queue == queue, Job.status.in_(LEASABLE), Job.run_after <= now]
        if types:
            conds.append(Job.type.in_(list(types)))
        stmt = select(Job).where(*conds).order_by(Job.priority, Job.id).limit(limit)

        leased: list[Job] = []
        if session.bind is not None and session.bind.dialect.name == "postgresql":
            rows = (await session.scalars(stmt.with_for_update(skip_locked=True))).all()
            for job in rows:
                self._mark_leased(job, worker_id, now, expires)
                leased.append(job)
        else:
            candidates = (await session.scalars(stmt.limit(limit * 4))).all()
            for job in candidates:
                if len(leased) >= limit:
                    break
                res = await session.execute(
                    update(Job)
                    .where(Job.id == job.id, Job.status.in_(LEASABLE))
                    .values(
                        status=JobStatus.leased,
                        lease_owner=worker_id,
                        lease_expires_at=expires,
                        attempts=Job.attempts + 1,
                        started_at=now,
                        updated_at=now,
                    )
                    .execution_options(synchronize_session=False)
                )
                if res.rowcount == 1:  # type: ignore[attr-defined]
                    await session.refresh(job)
                    leased.append(job)
        await session.commit()
        return leased

    @staticmethod
    def _mark_leased(job: Job, worker_id: str, now: Any, expires: Any) -> None:
        job.status = JobStatus.leased
        job.lease_owner = worker_id
        job.lease_expires_at = expires
        job.attempts += 1
        job.started_at = now

    async def _owned(self, session: AsyncSession, job_id: int, worker_id: str) -> Job:
        job = await session.get(Job, job_id, with_for_update=session.bind.dialect.name == "postgresql")  # type: ignore[union-attr]
        if job is None:
            raise NotFoundError(f"job {job_id} not found")
        if job.status != JobStatus.leased or job.lease_owner != worker_id:
            raise LeaseLostError(f"job {job_id} is not leased by {worker_id} (status={job.status})")
        return job

    async def heartbeat(self, session: AsyncSession, job_id: int, worker_id: str) -> Job:
        job = await self._owned(session, job_id, worker_id)
        job.lease_expires_at = utcnow() + timedelta(seconds=self.settings.job_lease_seconds)
        await session.commit()
        return job

    async def complete(self, session: AsyncSession, job_id: int, worker_id: str, result: dict[str, Any] | None) -> Job:
        job = await self._owned(session, job_id, worker_id)
        job.status = JobStatus.succeeded
        job.result = result or {}
        job.finished_at = utcnow()
        job.lease_owner = None
        job.lease_expires_at = None
        job.error = None
        await self._bump_worker(session, worker_id, ok=True)
        return job

    async def fail(
        self, session: AsyncSession, job_id: int, worker_id: str, error: str, *, retryable: bool = True
    ) -> Job:
        job = await self._owned(session, job_id, worker_id)
        self._apply_failure(job, error, retryable)
        await self._bump_worker(session, worker_id, ok=False)
        return job

    def _apply_failure(self, job: Job, error: str, retryable: bool) -> None:
        job.error = error[:4000]
        job.lease_owner = None
        job.lease_expires_at = None
        if retryable and job.attempts < job.max_attempts:
            job.status = JobStatus.failed
            job.run_after = utcnow() + timedelta(seconds=min(300, 5 * 2**job.attempts))
        else:
            job.status = JobStatus.dead
            job.finished_at = utcnow()
        log.warning("job %s #%s failed (%s): %s", job.type, job.id, job.status, error[:200])

    async def reap_expired(self, session: AsyncSession) -> list[Job]:
        """Return crashed/disconnected workers' jobs to the queue (or dead-letter them). Caller commits."""
        now = utcnow()
        rows = (
            await session.scalars(
                select(Job).where(Job.status == JobStatus.leased, Job.lease_expires_at < now).limit(100)
            )
        ).all()
        for job in rows:
            self._apply_failure(job, f"lease expired (worker {job.lease_owner})", retryable=True)
        return list(rows)

    async def retry(self, session: AsyncSession, job_id: int) -> Job:
        job = await session.get(Job, job_id)
        if job is None:
            raise NotFoundError(f"job {job_id} not found")
        if job.status not in (JobStatus.dead, JobStatus.failed):
            raise AppError(f"job {job_id} is {job.status}; only failed/dead jobs can be retried")
        job.status, job.attempts, job.run_after, job.error = JobStatus.queued, 0, utcnow(), None
        await session.commit()
        return job

    @staticmethod
    async def _bump_worker(session: AsyncSession, worker_id: str, *, ok: bool) -> None:
        col = Worker.jobs_done if ok else Worker.jobs_failed
        await session.execute(
            update(Worker)
            .where(Worker.id == worker_id)
            .values({col.key: col + 1, Worker.last_seen_at.key: utcnow()})
            .execution_options(synchronize_session=False)
        )

    # ------------------------------------------------------------------ introspection
    @staticmethod
    def pending_filter(asset_id: int) -> Any:
        return and_(Job.asset_id == asset_id, or_(*(Job.status == s for s in ACTIVE)))
