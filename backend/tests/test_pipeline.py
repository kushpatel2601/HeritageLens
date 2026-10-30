"""End-to-end processing DAG against a real (SQLite) database: ingest → extract → index → GPU results
settled through the same code path remote workers use → hybrid search."""

from __future__ import annotations

import io
from typing import Any

import numpy as np
import pytest
from PIL import Image
from sqlalchemy import func, select

from app.db.models import Asset, AssetStatus, Chunk, Entity, Job, JobStatus, Page, Site, Twin
from app.services.catalog import index_site
from app.services.ingest import IngestMeta, ingest_bytes
from app.services.pipeline import InvalidResultError, JobContext, settle_job
from app.services.search import SearchService
from app.services.twins import vav_stepwell, write_ply
from tests.conftest import drain

GUJARATI_JOURNAL = "પાટણ શહેરની રાણી કી વાવ સંવત ૧૧૨૦ માં રાણી ઉદયમતીએ બંધાવી હતી.\n\nવાવની દીવાલો પર સેંકડો શિલ્પો કોતરેલાં છે."
ENGLISH_JOURNAL = "Field notes, Patan 1998.\n\nThe Queen's Stepwell was silted up until the ASI excavations."


async def _site(ctx: JobContext) -> int:
    async with ctx.db.sessionmaker() as s:
        site = Site(
            slug="rani-ki-vav",
            name="Rani ki Vav",
            name_native="रानी की वाव",
            alt_names=["Queen's Stepwell", "રાણી કી વાવ"],
            category="stepwell",
            lat=23.8589,
            lon=72.1016,
            summary="An 11th-century stepwell in Patan.",
            tags=["unesco"],
        )
        await index_site(site, ctx.settings)
        s.add(site)
        await s.commit()
        return site.id


async def _ingest(ctx: JobContext, filename: str, data: bytes, **meta: Any) -> int:
    async with ctx.db.sessionmaker() as s:
        asset, created = await ingest_bytes(s, ctx.storage, ctx.queue, ctx.settings, filename, data, IngestMeta(**meta))
        await s.commit()
        assert created
        return asset.id


async def _gpu_job(ctx: JobContext, job_type: str, worker: str = "colab-t4") -> Job:
    async with ctx.db.sessionmaker() as s:
        [job] = await ctx.queue.lease(s, worker, "gpu", types=[job_type])
    return job


async def _settle(ctx: JobContext, job: Job, result: dict[str, object], worker: str = "colab-t4") -> Job:
    async with ctx.db.sessionmaker() as s:
        return await settle_job(ctx, s, job.id, worker, result)


def _jpeg(seed: int, size: tuple[int, int] = (320, 240)) -> bytes:
    """A smooth, photo-like synthetic image (pure noise has no stable perceptual hash)."""
    rng = np.random.default_rng(seed)
    coarse = Image.fromarray(rng.integers(0, 255, (6, 8, 3), dtype=np.uint8))
    buf = io.BytesIO()
    coarse.resize(size, Image.Resampling.BICUBIC).save(buf, "JPEG", quality=90)
    return buf.getvalue()


async def test_regional_journal_is_indexed_linked_and_sent_for_translation(ctx: JobContext) -> None:
    site_id = await _site(ctx)
    asset_id = await _ingest(ctx, "patan-notes.txt", GUJARATI_JOURNAL.encode())
    assert await drain(ctx) == 2  # extract + index

    async with ctx.db.sessionmaker() as s:
        asset = await s.get(Asset, asset_id)
        assert asset is not None
        assert (asset.status, asset.language, asset.site_id) == (AssetStatus.ready, "gu", site_id)
        assert (asset.lat, asset.lon, asset.era_year) == (23.8589, 72.1016, 1063)  # VS 1120 → 1063 CE
        chunks = (await s.scalars(select(Chunk).where(Chunk.asset_id == asset_id))).all()
        assert chunks and all(c.language == "gu" and c.embedding is not None for c in chunks)
        kinds = set((await s.scalars(select(Entity.kind).where(Entity.asset_id == asset_id))).all())
        assert kinds >= {"site", "date"}
        translate = await s.scalar(select(Job).where(Job.type == "translate"))
        assert translate is not None and translate.queue == "gpu" and translate.status == JobStatus.queued
        assert translate.payload["src_lang"] == "gu"
        assert {i["chunk_id"] for i in translate.payload["items"]} == {c.id for c in chunks}


async def test_gpu_translation_makes_regional_text_findable_in_english(ctx: JobContext) -> None:
    await _site(ctx)
    asset_id = await _ingest(ctx, "patan-notes.txt", GUJARATI_JOURNAL.encode())
    await drain(ctx)
    search = SearchService(ctx.settings)  # long-lived, like the API's: its in-memory index must not go stale
    async with ctx.db.sessionmaker() as s:
        assert (await search.search(s, "Udayamati built")).hits == []
    job = await _gpu_job(ctx, "translate")
    items = [
        {"chunk_id": i["chunk_id"], "translation": "Queen Udayamati built the Rani ki Vav of Patan in Samvat 1120."}
        for i in job.payload["items"]
    ]
    settled = await _settle(ctx, job, {"engine": "indictrans2-200M", "items": items})
    assert settled.status == JobStatus.succeeded
    assert settled.result == {"engine": "indictrans2-200M", "items": len(items)}
    assert await drain(ctx) == 1  # re-index with the translation

    async with ctx.db.sessionmaker() as s:
        chunk = await s.scalar(select(Chunk).where(Chunk.asset_id == asset_id))
        assert chunk is not None and chunk.translation_engine == "indictrans2-200M"
        # translation memory means re-indexing never asks the GPU again
        assert await s.scalar(select(func.count()).where(Job.type == "translate")) == 1
        resp = await search.search(s, "Udayamati built")
    assert resp.hits and resp.hits[0].asset.id == asset_id
    assert resp.hits[0].translation is not None


async def test_cross_script_search(ctx: JobContext) -> None:
    await _site(ctx)
    gu = await _ingest(ctx, "gu.txt", GUJARATI_JOURNAL.encode())
    en = await _ingest(ctx, "en.txt", ENGLISH_JOURNAL.encode())
    await drain(ctx)
    async with ctx.db.sessionmaker() as s:
        svc = SearchService(ctx.settings)
        latin = await svc.search(s, "rani ki vav")
        devanagari = await svc.search(s, "रानी की वाव")
        patan = await svc.search(s, "Patan")
    assert gu in {h.asset.id for h in latin.hits}
    assert gu in {h.asset.id for h in devanagari.hits}  # typed in Hindi script, found in Gujarati text
    assert devanagari.interpreted.script == "Deva"
    assert {h.asset.id for h in patan.hits} >= {gu, en}
    assert latin.sites and latin.sites[0].slug == "rani-ki-vav"


async def test_scan_waits_for_gpu_ocr_then_becomes_searchable(ctx: JobContext) -> None:
    await _site(ctx)
    asset_id = await _ingest(ctx, "inscription.jpg", _jpeg(1), kind="scan")
    assert await drain(ctx) == 1  # extract only; OCR is GPU work

    async with ctx.db.sessionmaker() as s:
        page = await s.scalar(select(Page).where(Page.asset_id == asset_id))
        asset = await s.get(Asset, asset_id)
        assert page is not None and page.needs_ocr and page.image_key
        assert asset is not None and asset.status == AssetStatus.processing

    job = await _gpu_job(ctx, "ocr")
    assert job.payload["pages"] == [{"page_no": 1, "image_key": page.image_key}]
    assert await ctx.storage.exists(job.payload["pages"][0]["image_key"])
    text = "संवत ११२० में रानी उदयमती ने यह वाव बनवाई।"
    await _settle(ctx, job, {"engine": "surya", "pages": [{"page_no": 1, "text": text, "confidence": 0.91}]})
    await drain(ctx)

    async with ctx.db.sessionmaker() as s:
        page = await s.scalar(select(Page).where(Page.asset_id == asset_id))
        asset = await s.get(Asset, asset_id)
        ocr_job = await s.get(Job, job.id)
        assert page is not None and asset is not None and ocr_job is not None
        assert (page.text, page.source, page.ocr_engine, page.needs_ocr, page.language) == (
            text,
            "ocr",
            "surya",
            False,
            "hi",
        )
        assert asset.status == AssetStatus.ready and asset.era_year == 1063
        assert ocr_job.result == {"engine": "surya", "pages": 1, "chars": len(text), "mean_confidence": 0.91}
        resp = await SearchService(ctx.settings).search(s, "udayamati")
    assert [h.asset.id for h in resp.hits] == [asset_id]


@pytest.mark.parametrize(
    "bad",
    [
        {"engine": "surya", "pages": [{"page_no": 1, "text": "x", "confidence": 7}]},
        {"engine": "surya", "pages": [{"page_no": 0, "text": "x"}]},
        {"pages": []},
    ],
)
async def test_invalid_gpu_results_are_dead_lettered(ctx: JobContext, bad: dict[str, object]) -> None:
    asset_id = await _ingest(ctx, "scan.png", _jpeg(2), kind="scan")
    await drain(ctx)
    job = await _gpu_job(ctx, "ocr")
    with pytest.raises(InvalidResultError):
        await _settle(ctx, job, bad)
    async with ctx.db.sessionmaker() as s:
        dead = await s.get(Job, job.id)
        asset = await s.get(Asset, asset_id)
        page = await s.scalar(select(Page).where(Page.asset_id == asset_id))
    assert dead is not None and dead.status == JobStatus.dead and "ocr result rejected" in (dead.error or "")
    assert asset is not None and asset.status == AssetStatus.failed  # OCR blocks the asset
    assert page is not None and page.needs_ocr and page.text == ""  # nothing half-applied


async def test_translation_for_unrequested_chunk_is_rejected(ctx: JobContext) -> None:
    await _ingest(ctx, "gu.txt", GUJARATI_JOURNAL.encode())
    await drain(ctx)
    job = await _gpu_job(ctx, "translate")
    with pytest.raises(InvalidResultError, match="not requested"):
        await _settle(ctx, job, {"engine": "nllb", "items": [{"chunk_id": 987654, "translation": "spoofed"}]})


async def test_captions_never_overwrite_human_text(ctx: JobContext) -> None:
    ai = await _ingest(ctx, "a.jpg", _jpeg(3))
    human = await _ingest(ctx, "b.jpg", _jpeg(4), caption="Carved Vishnu panel, west wall", contributor="Fellow")
    await drain(ctx)
    async with ctx.db.sessionmaker() as s:
        human_asset = await s.get(Asset, human)
        assert human_asset is not None and human_asset.caption_source == "contributor"
        jobs = (await s.scalars(select(Job).where(Job.type == "caption"))).all()
    assert [j.asset_id for j in jobs] == [ai]  # nothing requested for the human-captioned photo
    job = await _gpu_job(ctx, "caption")
    await _settle(ctx, job, {"engine": "blip-large", "caption": "a carved stone stepwell wall"})
    async with ctx.db.sessionmaker() as s:
        photo = await s.get(Asset, ai)
    assert photo is not None and (photo.caption, photo.caption_source) == ("a carved stone stepwell wall", "blip-large")


async def test_photo_text_indexes_each_distinct_line_once(ctx: JobContext) -> None:
    site_id = await _site(ctx)
    asset_id = await _ingest(
        ctx, "vav.jpg", _jpeg(6), title="Rani ki Vav, Patan", caption="  rani ki vav,\nPATAN ", site_id=site_id
    )
    await drain(ctx)
    async with ctx.db.sessionmaker() as s:
        [chunk] = (await s.scalars(select(Chunk).where(Chunk.asset_id == asset_id))).all()
    assert chunk.text == "Rani ki Vav, Patan\n\nSite: Rani ki Vav"


async def test_near_duplicate_photos_inherit_site(ctx: JobContext) -> None:
    site_id = await _site(ctx)
    original = await _ingest(ctx, "vav.jpg", _jpeg(5, (640, 480)), site_id=site_id)
    await drain(ctx)
    smaller = Image.open(io.BytesIO(_jpeg(5, (640, 480)))).resize((320, 240))
    buf = io.BytesIO()
    smaller.save(buf, "JPEG", quality=70)
    copy = await _ingest(ctx, "slide-export.jpg", buf.getvalue())
    await drain(ctx)
    async with ctx.db.sessionmaker() as s:
        asset = await s.get(Asset, copy)
    assert asset is not None and asset.site_id == site_id
    assert asset.meta["site_link"] == {"method": "near-duplicate", "asset_id": original}


async def test_reconstruction_artifacts_must_belong_to_the_job(ctx: JobContext) -> None:
    site_id = await _site(ctx)
    async with ctx.db.sessionmaker() as s:
        job = await ctx.queue.enqueue(s, "reconstruct3d", {"site_id": site_id, "images": []}, site_id=site_id)
        await s.commit()
    leased = await _gpu_job(ctx, "reconstruct3d")
    assert leased.id == job.id

    foreign = {"artifact_key": "twins/site-1/job-999/x.ply", "format": "ply", "method": "depth-relief"}
    with pytest.raises(InvalidResultError, match="does not belong"):
        await _settle(ctx, leased, foreign)

    async with ctx.db.sessionmaker() as s:
        job = await ctx.queue.enqueue(s, "reconstruct3d", {"site_id": site_id, "images": []}, site_id=site_id)
        await s.commit()
    leased = await _gpu_job(ctx, "reconstruct3d")
    key = f"twins/site-{site_id}/job-{leased.id}/relief.ply"
    missing = {"artifact_key": key, "format": "ply", "method": "depth-relief"}
    with pytest.raises(InvalidResultError, match="not uploaded"):
        await _settle(ctx, leased, missing)

    async with ctx.db.sessionmaker() as s:
        job = await ctx.queue.enqueue(s, "reconstruct3d", {"site_id": site_id, "images": []}, site_id=site_id)
        await s.commit()
    leased = await _gpu_job(ctx, "reconstruct3d")
    key = f"twins/site-{site_id}/job-{leased.id}/relief.ply"
    await ctx.storage.put(key, write_ply(vav_stepwell()))
    ok = {"artifact_key": key, "format": "ply", "method": "depth-relief", "point_count": 10, "source_asset_ids": [1]}
    assert (await _settle(ctx, leased, ok)).status == JobStatus.succeeded
    async with ctx.db.sessionmaker() as s:
        [twin] = (await s.scalars(select(Twin))).all()
    assert (twin.site_id, twin.storage_key, twin.title) == (site_id, key, "Depth relief from 1 photo")
    assert twin.meta == {"job_id": leased.id, "provenance": "gpu-worker"}
