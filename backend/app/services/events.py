"""Live pipeline events for the UI (Server-Sent Events).

Workers may run in other processes or on remote GPUs, so in-process signals are not enough. One
poller per API process reads recently-updated jobs/assets from the database (indexed `updated_at`)
and fans them out to every connected client: O(1) queries per tick regardless of client count.
A short overlap window plus (id, updated_at) de-duplication tolerates commit-ordering skew.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select

from app.db.base import utcnow
from app.db.models import Asset, Job
from app.db.session import Database
from app.services.jobs import labelled_jobs

log = logging.getLogger(__name__)

OVERLAP = timedelta(seconds=3)
QUEUE_SIZE = 256


def job_event(
    j: Job, asset_title: str | None = None, site_name: str | None = None, site_slug: str | None = None
) -> dict[str, Any]:
    return {
        "id": j.id,
        "type": j.type,
        "queue": j.queue,
        "status": j.status,
        "attempts": j.attempts,
        "asset_id": j.asset_id,
        "asset_title": asset_title,
        "site_id": j.site_id,
        "site_name": site_name,
        "site_slug": site_slug,
        "error": j.error,
        "result": j.result,
        "updated_at": j.updated_at.isoformat(),
    }


def asset_event(a: Asset) -> dict[str, Any]:
    return {
        "id": a.id,
        "kind": a.kind,
        "title": a.title,
        "status": a.status,
        "error": a.error,
        "language": a.language,
        "site_id": a.site_id,
        "lat": a.lat,
        "lon": a.lon,
        "thumb_url": f"/api/v1/assets/{a.id}/thumbnail" if a.thumb_key else None,
        "updated_at": a.updated_at.isoformat(),
    }


class EventHub:
    def __init__(self, db: Database, interval: float = 1.0) -> None:
        self.db = db
        self.interval = interval
        self._subs: set[asyncio.Queue[tuple[str, dict[str, Any]]]] = set()
        self._task: asyncio.Task[None] | None = None
        self._cursor: datetime = utcnow()
        self._seen: dict[tuple[str, int], datetime] = {}

    @property
    def subscribers(self) -> int:
        return len(self._subs)

    @contextlib.asynccontextmanager
    async def subscribe(self) -> AsyncIterator[asyncio.Queue[tuple[str, dict[str, Any]]]]:
        q: asyncio.Queue[tuple[str, dict[str, Any]]] = asyncio.Queue(QUEUE_SIZE)
        self._subs.add(q)
        if self._task is None or self._task.done():
            self._cursor = utcnow() - OVERLAP
            self._task = asyncio.create_task(self._run(), name="event-hub")
        try:
            yield q
        finally:
            self._subs.discard(q)

    async def close(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    def publish(self, kind: str, data: dict[str, Any]) -> None:
        for q in list(self._subs):
            try:
                q.put_nowait((kind, data))
            except asyncio.QueueFull:  # slow consumer: drop oldest, keep the stream live
                with contextlib.suppress(asyncio.QueueEmpty):
                    q.get_nowait()
                q.put_nowait((kind, data))

    async def _run(self) -> None:
        while self._subs:
            try:
                await self._tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("event poll failed")
            await asyncio.sleep(self.interval)

    async def _tick(self) -> None:
        since = self._cursor - OVERLAP
        async with self.db.sessionmaker() as s:
            jobs = (
                await s.execute(labelled_jobs().where(Job.updated_at > since).order_by(Job.updated_at).limit(500))
            ).all()
            assets = (
                await s.scalars(select(Asset).where(Asset.updated_at > since).order_by(Asset.updated_at).limit(500))
            ).all()
        newest = self._cursor
        updates: list[tuple[str, Job | Asset, dict[str, Any]]] = [
            ("job", j, job_event(j, title, site_name, site_slug)) for j, title, site_name, site_slug in jobs
        ] + [("asset", a, asset_event(a)) for a in assets]
        for kind, row, payload in updates:
            key = (kind, row.id)
            if self._seen.get(key) == row.updated_at:
                continue
            self._seen[key] = row.updated_at
            newest = max(newest, row.updated_at)
            self.publish(kind, payload)
        self._cursor = newest
        horizon = newest - OVERLAP * 4
        if len(self._seen) > 5000:
            self._seen = {k: v for k, v in self._seen.items() if v >= horizon}
