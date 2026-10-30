"""Live pipeline events: one database poll per tick fans job/asset updates out to every subscriber."""

from __future__ import annotations

import asyncio
from typing import Any

from app.db.models import Site
from app.services.events import EventHub
from app.services.ingest import IngestMeta, ingest_bytes
from app.services.pipeline import JobContext


async def test_job_events_name_the_asset_or_site_they_work_on(ctx: JobContext) -> None:
    async with ctx.db.sessionmaker() as s:
        site = Site(slug="adalaj", name="Adalaj Stepwell", category="stepwell", lat=23.1667, lon=72.5797)
        s.add(site)
        await s.flush()
        asset, _ = await ingest_bytes(
            s, ctx.storage, ctx.queue, ctx.settings, "note.txt", b"Field notes", IngestMeta(title="Field notes")
        )
        twin_job = await ctx.queue.enqueue(s, "reconstruct3d", {"site_id": site.id}, site_id=site.id)
        await s.commit()
        asset_id, site_id, twin_job_id = asset.id, site.id, twin_job.id

    hub = EventHub(ctx.db, interval=0.02)
    jobs: dict[int, dict[str, Any]] = {}
    assets: dict[int, dict[str, Any]] = {}
    try:
        async with hub.subscribe() as queue:
            while twin_job_id not in jobs or not any(j["asset_id"] == asset_id for j in jobs.values()):
                kind, data = await asyncio.wait_for(queue.get(), timeout=5)
                (jobs if kind == "job" else assets)[data["id"]] = data
            assert hub.subscribers == 1
    finally:
        await hub.close()

    [extract] = [j for j in jobs.values() if j["asset_id"] == asset_id]
    assert (extract["type"], extract["asset_title"], extract["site_name"]) == ("extract", "Field notes", None)
    twin = jobs[twin_job_id]
    assert (twin["site_id"], twin["site_name"], twin["site_slug"], twin["asset_title"]) == (
        site_id,
        "Adalaj Stepwell",
        "adalaj",
        None,
    )
    assert hub.subscribers == 0
