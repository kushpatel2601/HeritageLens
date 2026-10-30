"""Durable lease queue: routing, dedupe, priority, at-most-one owner, backoff, dead-letter, reaping."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import update

from app.core.errors import AppError, NotFoundError
from app.db.base import utcnow
from app.db.models import Job, JobStatus, Worker
from app.services.jobs import JobQueue, LeaseLostError
from app.services.pipeline import JobContext, reap
from tests.conftest import make_settings


async def _enqueue(ctx: JobContext, job_type: str = "index", **kw: Any) -> int:
    async with ctx.db.sessionmaker() as s:
        job = await ctx.queue.enqueue(s, job_type, {"asset_id": 1}, **kw)
        await s.commit()
        return job.id


async def _job(ctx: JobContext, job_id: int) -> Job:
    async with ctx.db.sessionmaker() as s:
        job = await s.get(Job, job_id)
        assert job is not None
        return job


async def _lease(ctx: JobContext, worker: str = "w1", queue: str = "cpu", **kw: Any) -> list[Job]:
    async with ctx.db.sessionmaker() as s:
        return await ctx.queue.lease(s, worker, queue, **kw)


def test_routing(tmp_path: Path) -> None:
    q = JobQueue(make_settings(tmp_path, gpu_fallback_to_cpu=False))
    assert q.route("extract") == "cpu"
    assert q.route("index") == "cpu"
    assert {q.route(t) for t in ("ocr", "translate", "caption", "reconstruct3d")} == {"gpu"}
    q._cpu_fallback["ocr"] = True  # pretend tesseract is installed
    assert q.route("ocr") == "gpu"  # fallback disabled
    q2 = JobQueue(make_settings(tmp_path, gpu_fallback_to_cpu=True))
    q2._cpu_fallback["ocr"] = True
    assert q2.route("ocr") == "cpu"
    assert q2.route("translate") == "gpu"  # no CPU implementation


async def test_dedupe_coalesces_pending_jobs_but_not_running_ones(ctx: JobContext) -> None:
    a = await _enqueue(ctx, dedupe_key="index:1")
    b = await _enqueue(ctx, dedupe_key="index:1")
    assert a == b
    [leased] = await _lease(ctx)
    assert leased.id == a
    c = await _enqueue(ctx, dedupe_key="index:1")
    assert c != a  # newer inputs get processed after the running job


async def test_priority_then_fifo(ctx: JobContext) -> None:
    low = await _enqueue(ctx, priority=200)
    first = await _enqueue(ctx, priority=10)
    second = await _enqueue(ctx, priority=10)
    leased = await _lease(ctx, limit=3)
    assert [j.id for j in leased] == [first, second, low]
    assert all(j.status == JobStatus.leased and j.attempts == 1 and j.lease_owner == "w1" for j in leased)


async def test_lease_filters_by_queue_and_type(ctx: JobContext) -> None:
    ocr = await _enqueue(ctx, "ocr")
    idx = await _enqueue(ctx, "index")
    assert [j.id for j in await _lease(ctx, queue="cpu", types=["ocr"])] == []
    assert [j.id for j in await _lease(ctx, queue="gpu", types=["caption"])] == []
    assert [j.id for j in await _lease(ctx, queue="gpu", types=["ocr"])] == [ocr]
    assert [j.id for j in await _lease(ctx, queue="cpu")] == [idx]


async def test_concurrent_workers_never_share_a_job(ctx: JobContext) -> None:
    ids = {await _enqueue(ctx) for _ in range(12)}
    batches = await asyncio.gather(*(_lease(ctx, worker=f"w{i}", limit=4) for i in range(6)))
    leased = [j.id for batch in batches for j in batch]
    assert len(leased) == len(set(leased)) == 12
    assert set(leased) == ids


async def test_ownership_is_enforced(ctx: JobContext) -> None:
    job_id = await _enqueue(ctx)
    await _lease(ctx, worker="owner")
    async with ctx.db.sessionmaker() as s:
        with pytest.raises(LeaseLostError):
            await ctx.queue.heartbeat(s, job_id, "intruder")
        with pytest.raises(LeaseLostError):
            await ctx.queue.complete(s, job_id, "intruder", {})
        with pytest.raises(NotFoundError):
            await ctx.queue.heartbeat(s, 999_999, "owner")
        before = (await _job(ctx, job_id)).lease_expires_at
        await asyncio.sleep(0.01)
        after = (await ctx.queue.heartbeat(s, job_id, "owner")).lease_expires_at
        assert before is not None and after is not None and after > before


async def test_complete_bumps_worker_stats(ctx: JobContext) -> None:
    async with ctx.db.sessionmaker() as s:
        s.add(Worker(id="w1", name="w1", queue="cpu", device="cpu", capabilities=[]))
        await s.commit()
    job_id = await _enqueue(ctx)
    await _lease(ctx)
    async with ctx.db.sessionmaker() as s:
        await ctx.queue.complete(s, job_id, "w1", {"ok": True})
        await s.commit()
        worker = await s.get(Worker, "w1")
        assert worker is not None and worker.jobs_done == 1
    job = await _job(ctx, job_id)
    assert (job.status, job.result, job.lease_owner) == (JobStatus.succeeded, {"ok": True}, None)


async def test_failure_backs_off_then_dead_letters(ctx: JobContext) -> None:
    job_id = await _enqueue(ctx)
    for attempt in range(1, ctx.settings.job_max_attempts + 1):
        [job] = await _lease(ctx)
        assert job.attempts == attempt
        async with ctx.db.sessionmaker() as s:
            job = await ctx.queue.fail(s, job_id, "w1", f"boom {attempt}")
            await s.commit()
        if attempt < ctx.settings.job_max_attempts:
            assert job.status == JobStatus.failed
            delay = (job.run_after - utcnow()).total_seconds()
            assert 0 < delay <= 5 * 2**attempt
            assert await _lease(ctx) == []  # not before run_after
            async with ctx.db.sessionmaker() as s:
                await s.execute(update(Job).where(Job.id == job_id).values(run_after=utcnow()))
                await s.commit()
    job = await _job(ctx, job_id)
    assert (job.status, job.error) == (JobStatus.dead, "boom 3")
    assert job.finished_at is not None


async def test_non_retryable_failure_is_dead_immediately(ctx: JobContext) -> None:
    job_id = await _enqueue(ctx)
    await _lease(ctx)
    async with ctx.db.sessionmaker() as s:
        job = await ctx.queue.fail(s, job_id, "w1", "invalid result", retryable=False)
        await s.commit()
    assert job.status == JobStatus.dead and job.attempts == 1


async def test_reaper_requeues_jobs_from_vanished_workers(ctx: JobContext) -> None:
    job_id = await _enqueue(ctx)
    await _lease(ctx, worker="crashed")
    async with ctx.db.sessionmaker() as s:
        await s.execute(update(Job).where(Job.id == job_id).values(lease_expires_at=utcnow() - timedelta(seconds=1)))
        await s.commit()
    assert await reap(ctx) == 1
    job = await _job(ctx, job_id)
    assert job.status == JobStatus.failed
    assert job.lease_owner is None
    assert "lease expired (worker crashed)" in (job.error or "")
    assert await reap(ctx) == 0


async def test_manual_retry(ctx: JobContext) -> None:
    job_id = await _enqueue(ctx)
    async with ctx.db.sessionmaker() as s:
        with pytest.raises(AppError):
            await ctx.queue.retry(s, job_id)  # queued jobs cannot be retried
    await _lease(ctx)
    async with ctx.db.sessionmaker() as s:
        await ctx.queue.fail(s, job_id, "w1", "x", retryable=False)
        await s.commit()
        job = await ctx.queue.retry(s, job_id)
    assert (job.status, job.attempts, job.error) == (JobStatus.queued, 0, None)
    assert [j.id for j in await _lease(ctx)] == [job_id]
