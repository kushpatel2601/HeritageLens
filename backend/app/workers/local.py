"""In-process / standalone CPU worker.

The same lease protocol is spoken by remote GPU workers over HTTP; this worker just calls the queue
directly. Scale out by running more `heritagelens worker` processes:
leases guarantee each job is processed by exactly one live worker at a time.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import platform
import socket
import uuid
from typing import Any

from app.db.base import utcnow
from app.db.models import Job, Worker
from app.services.jobs import LeaseLostError
from app.services.pipeline import HANDLERS, InvalidResultError, JobContext, fail_job, get_handler, reap, settle_job

log = logging.getLogger(__name__)

HOUSEKEEPING_SECONDS = 10.0


class LocalWorker:
    def __init__(self, ctx: JobContext, *, name: str | None = None, queue: str = "cpu", concurrency: int = 2) -> None:
        self.ctx = ctx
        self.queue = queue
        self.concurrency = max(1, concurrency)
        self.id = f"{queue}-{socket.gethostname()[:20]}-{uuid.uuid4().hex[:8]}"
        self.name = name or f"{queue} worker ({platform.node() or 'local'}, pid {os.getpid()})"
        self._stopping = asyncio.Event()
        self._tasks: list[asyncio.Task[Any]] = []

    @property
    def job_types(self) -> list[str]:
        return sorted(t for t, h in HANDLERS.items() if h.runs_locally(self.ctx))

    # ---------------------------------------------------------------- lifecycle
    async def start(self) -> None:
        await self._register()
        self._stopping.clear()
        self._tasks = [asyncio.create_task(self._loop(i), name=f"worker-{i}") for i in range(self.concurrency)]
        self._tasks.append(asyncio.create_task(self._housekeeping(), name="worker-housekeeping"))
        log.info("worker %s started: queue=%s types=%s x%d", self.id, self.queue, self.job_types, self.concurrency)

    async def stop(self) -> None:
        self._stopping.set()
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        log.info("worker %s stopped", self.id)

    def request_stop(self) -> None:
        """Signal-handler safe: `run_forever` returns after in-flight jobs are cancelled."""
        self._stopping.set()

    async def run_forever(self) -> None:
        await self.start()
        try:
            await self._stopping.wait()
        finally:
            await self.stop()

    async def drain(self, max_jobs: int = 10_000) -> int:
        """Process jobs until the queue is idle (tests, seeding, batch backfills)."""
        await self._register()
        done = 0
        while done < max_jobs:
            job = await self._lease_one()
            if job is None:
                return done
            await self.process(job)
            done += 1
        return done

    # ---------------------------------------------------------------- internals
    async def _register(self) -> None:
        async with self.ctx.db.sessionmaker() as s:
            row = await s.get(Worker, self.id)
            if row is None:
                s.add(Worker(id=self.id, name=self.name, queue=self.queue, device="cpu", capabilities=self.job_types))
            else:
                row.last_seen_at, row.capabilities = utcnow(), self.job_types
            await s.commit()

    async def _lease_one(self) -> Job | None:
        async with self.ctx.db.sessionmaker() as s:
            jobs = await self.ctx.queue.lease(s, self.id, self.queue, types=self.job_types, limit=1)
        return jobs[0] if jobs else None

    async def _loop(self, slot: int) -> None:
        poll = self.ctx.settings.worker_poll_seconds
        while not self._stopping.is_set():
            try:
                job = await self._lease_one()
                if job is None:
                    with contextlib.suppress(TimeoutError):
                        await asyncio.wait_for(self._stopping.wait(), timeout=poll)
                    continue
                await self.process(job)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("worker slot %d crashed; continuing", slot)
                await asyncio.sleep(poll)

    async def process(self, job: Job) -> None:
        handler = get_handler(job.type)
        heartbeat = asyncio.create_task(self._heartbeat(job.id))
        try:
            result = await handler.run(self.ctx, job)
        except Exception as exc:
            log.exception("job %s #%s failed", job.type, job.id)
            async with self.ctx.db.sessionmaker() as s:
                with contextlib.suppress(LeaseLostError):
                    await fail_job(self.ctx, s, job.id, self.id, f"{type(exc).__name__}: {exc}")
            return
        finally:
            heartbeat.cancel()
        async with self.ctx.db.sessionmaker() as s:
            with contextlib.suppress(InvalidResultError, LeaseLostError):
                await settle_job(self.ctx, s, job.id, self.id, result)

    async def _heartbeat(self, job_id: int) -> None:
        interval = max(5.0, self.ctx.settings.job_lease_seconds / 3)
        while True:
            await asyncio.sleep(interval)
            try:
                async with self.ctx.db.sessionmaker() as s:
                    await self.ctx.queue.heartbeat(s, job_id, self.id)
            except LeaseLostError:
                log.warning("lost lease on job %s", job_id)
                return
            except Exception:
                log.exception("heartbeat for job %s failed", job_id)

    async def _housekeeping(self) -> None:
        while not self._stopping.is_set():
            try:
                async with self.ctx.db.sessionmaker() as s:
                    row = await s.get(Worker, self.id)
                    if row is not None:
                        row.last_seen_at = utcnow()
                    await s.commit()
                reaped = await reap(self.ctx)
                if reaped:
                    log.info("re-queued %d jobs with expired leases", reaped)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("housekeeping failed")
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._stopping.wait(), timeout=HOUSEKEEPING_SECONDS)
