"""The bundled sample archive loads offline, is fully searchable, and re-seeding is a no-op."""

from __future__ import annotations

from sqlalchemy import func, select

from app.db.models import Asset, AssetStatus, Chunk, Job, JobStatus, Site, Twin
from app.seed.loader import run_seed
from app.services.pipeline import JobContext
from app.services.search import SearchService


async def _counts(ctx: JobContext) -> dict[str, int]:
    async with ctx.db.sessionmaker() as s:
        return {
            m.__tablename__: int(await s.scalar(select(func.count()).select_from(m)) or 0)
            for m in (Site, Asset, Chunk, Twin, Job)
        }


async def test_seed_is_offline_complete_and_idempotent(ctx: JobContext) -> None:
    first = await run_seed(ctx, offline=True)
    assert first.sites == 17 and first.journeys == 3
    assert first.assets_created > 0 and first.twins_created > 0 and first.jobs_processed > 0
    assert first.photos_unavailable == []  # every sample photo ships in the repo

    async with ctx.db.sessionmaker() as s:
        statuses = dict((await s.execute(select(Asset.status, func.count()).group_by(Asset.status))).all())
        assert set(statuses) <= {AssetStatus.ready, AssetStatus.processing}
        # Only the untranscribed scan waits, for a GPU worker to OCR it.
        gpu = (await s.scalars(select(Job.type).where(Job.queue == "gpu", Job.status == JobStatus.queued))).all()
        assert "ocr" in gpu
        assert await s.scalar(select(func.count()).where(Job.status == JobStatus.dead)) == 0
        res = await SearchService(ctx.settings).search(s, "chand baori")
        assert res.sites and res.sites[0].slug == "chand-baori"

    before = await _counts(ctx)
    second = await run_seed(ctx, offline=True)
    assert second.assets_created == 0 and second.twins_created == 0
    assert second.assets_existing == first.assets_created + first.assets_existing
    assert await _counts(ctx) == before
