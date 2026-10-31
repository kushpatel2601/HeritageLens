from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import func, select, text

from app import __version__
from app.api.deps import ServicesDep, SessionDep
from app.db.base import utcnow
from app.db.models import Asset, Chunk, Entity, Job, JobStatus, Journey, Page, Site, Twin, Worker
from app.schemas.catalog import Health, Stats
from app.services.embeddings import aget_text_embedder

router = APIRouter(tags=["ops"])

SSE_KEEPALIVE = 15.0


async def _workers_online(session: SessionDep, offline_after: int) -> dict[str, int]:
    since = utcnow() - timedelta(seconds=offline_after)
    rows = (
        await session.execute(
            select(Worker.queue, func.count()).where(Worker.last_seen_at >= since).group_by(Worker.queue)
        )
    ).all()
    return {q: int(n) for q, n in rows}


@router.get("/health", summary="Liveness probe")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready", response_model=Health, summary="Readiness probe (DB, storage, workers)")
async def ready(services: ServicesDep, session: SessionDep) -> JSONResponse:
    checks: dict[str, str] = {}
    try:
        await session.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:
        checks["database"] = f"error: {type(exc).__name__}"
    try:
        await services.storage.exists("health/probe")
        checks["storage"] = "ok"
    except Exception as exc:
        checks["storage"] = f"error: {type(exc).__name__}"
    workers = (
        await _workers_online(session, services.settings.worker_offline_after_seconds)
        if checks["database"] == "ok"
        else {}
    )
    checks["gpu_workers"] = "ok" if workers.get("gpu") else "none online (GPU jobs will wait in the queue)"
    healthy = checks["database"] == "ok" and checks["storage"] == "ok"
    body = Health(
        status="ok" if healthy else "degraded",
        version=__version__,
        database=services.db.dialect,
        embedder=(await aget_text_embedder(services.settings)).name,
        workers_online=workers,
        checks=checks,
    )
    return JSONResponse(body.model_dump(), status_code=200 if healthy else 503)


@router.get("/stats", response_model=Stats, summary="Archive & pipeline counters for the dashboard")
async def stats(services: ServicesDep, session: SessionDep) -> Stats:
    async def count(model: type, *conds: object) -> int:
        return int(await session.scalar(select(func.count()).select_from(model).where(*conds)) or 0)  # type: ignore[arg-type]

    async def group(col: object, *conds: object) -> dict[str, int]:
        rows = (await session.execute(select(col, func.count()).where(*conds).group_by(col))).all()  # type: ignore[call-overload]
        return {str(k): int(v) for k, v in rows if k is not None}

    depth = (
        await session.execute(
            select(Job.queue, func.count())
            .where(Job.status.in_([JobStatus.queued, JobStatus.failed]))
            .group_by(Job.queue)
        )
    ).all()
    online = await _workers_online(session, services.settings.worker_offline_after_seconds)
    return Stats(
        sites=await count(Site),
        journeys=await count(Journey),
        assets=await count(Asset),
        assets_by_kind=await group(Asset.kind),
        assets_by_status=await group(Asset.status),
        pages=await count(Page),
        ocr_pages=await count(Page, Page.source == "ocr"),
        chunks=await count(Chunk),
        translated_chunks=await count(Chunk, Chunk.translation.is_not(None), Chunk.translation != ""),
        languages=await group(Chunk.language),
        entities=await count(Entity),
        geotagged_assets=await count(Asset, Asset.lat.is_not(None)),
        twins=await count(Twin),
        jobs_by_status=await group(Job.status),
        queue_depth={q: int(n) for q, n in depth},
        workers_online=sum(online.values()),
        embedder=(await aget_text_embedder(services.settings)).name,
        database=services.db.dialect,
    )


@router.get("/events", summary="Server-Sent Events stream of job & asset updates")
async def events(
    request: Request, services: ServicesDep, asset_id: Annotated[int | None, Query()] = None
) -> StreamingResponse:
    async def stream() -> AsyncIterator[str]:
        yield "retry: 3000\n\n"
        async with services.events.subscribe() as q:
            while True:
                if await request.is_disconnected():
                    return
                try:
                    kind, data = await asyncio.wait_for(q.get(), timeout=SSE_KEEPALIVE)
                except TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                if asset_id is not None and (data["id"] if kind == "asset" else data.get("asset_id")) != asset_id:
                    continue
                yield f"event: {kind}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )
