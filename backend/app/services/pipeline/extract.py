"""Stage 1 - extraction: turn raw bytes into pages, thumbnails, geo/EXIF facts and child assets."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import delete, select

from app.db.models import Asset, AssetKind, AssetStatus, Job, Page, Site
from app.services.extractors.files import decode_text
from app.services.extractors.images import hamming, inspect_image, make_thumbnail, to_png
from app.services.extractors.office import EmbeddedImage, extract_docx, extract_pptx
from app.services.extractors.pdf import extract_pdf
from app.services.geo import nearest
from app.services.ingest import IngestMeta, ingest_bytes
from app.services.pipeline.base import Handler, JobContext, enqueue_index, register
from app.services.text.scripts import detect_language

log = logging.getLogger(__name__)

SITE_LINK_KM = 1.5
NEAR_DUPLICATE_BITS = 4
WEB_IMAGE_FORMATS = {"JPEG", "PNG", "WEBP"}
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


@dataclass(slots=True)
class PageDraft:
    page_no: int
    text: str = ""
    needs_ocr: bool = False
    image: bytes | None = None  # rendered page to store under pages/{asset}/{n}.png
    image_key: str | None = None  # or reuse an existing stored object
    source: str = "native"


@dataclass(slots=True)
class Extraction:
    pages: list[PageDraft] = field(default_factory=list)
    updates: dict[str, Any] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)
    thumbnail: bytes | None = None
    children: list[EmbeddedImage] = field(default_factory=list)


@dataclass(slots=True)
class _SiteRef:
    id: int
    lat: float
    lon: float


async def _image_facts(asset: Asset, data: bytes, out: Extraction) -> Any:
    info = await asyncio.to_thread(inspect_image, data)
    out.thumbnail = await asyncio.to_thread(make_thumbnail, data)
    out.updates.update(width=info.width, height=info.height, phash=info.dhash, captured_at=info.captured_at)
    if info.camera:
        out.meta["camera"] = info.camera
    if info.lat is not None and info.lon is not None and asset.lat is None:
        out.updates.update(lat=info.lat, lon=info.lon, geo_source="exif")
    return info


async def _extract_photo(ctx: JobContext, asset: Asset, data: bytes) -> Extraction:
    out = Extraction()
    await _image_facts(asset, data, out)
    return out


async def _extract_scan(ctx: JobContext, asset: Asset, data: bytes) -> Extraction:
    out = Extraction()
    info = await _image_facts(asset, data, out)
    page = PageDraft(page_no=1)
    if info.format in WEB_IMAGE_FORMATS:
        page.image_key = asset.storage_key
    else:
        page.image = await asyncio.to_thread(to_png, data)
    transcript = (asset.meta or {}).get("transcript")
    if transcript:  # curated transcription shipped with the seed archive
        page.text, page.source = transcript, "seed"
    else:
        page.needs_ocr = True
    out.pages.append(page)
    return out


async def _extract_pdf(ctx: JobContext, asset: Asset, data: bytes) -> Extraction:
    out = Extraction()
    pages = await asyncio.to_thread(extract_pdf, data, ctx.settings.max_pdf_pages)
    for p in pages:
        out.pages.append(PageDraft(page_no=p.page_no, text=p.text, needs_ocr=p.needs_ocr, image=p.image_png))
    if pages and pages[0].image_png:
        out.thumbnail = await asyncio.to_thread(make_thumbnail, pages[0].image_png)
    out.meta["page_count"] = len(pages)
    return out


async def _extract_deck(ctx: JobContext, asset: Asset, data: bytes) -> Extraction:
    out = Extraction()
    deck = await asyncio.to_thread(extract_pptx, data)
    out.pages = [PageDraft(page_no=s.number, text=s.as_text()) for s in deck.slides]
    out.children = deck.images
    if deck.images:
        out.thumbnail = await asyncio.to_thread(make_thumbnail, deck.images[0].data)
    out.meta.update(slide_count=len(deck.slides), rescued_images=len(deck.images))
    return out


async def _extract_text(ctx: JobContext, asset: Asset, data: bytes) -> Extraction:
    text = await asyncio.to_thread(extract_docx, data) if asset.mime == DOCX_MIME else decode_text(data)
    return Extraction(pages=[PageDraft(page_no=1, text=text.strip())])


EXTRACTORS = {
    AssetKind.photo: _extract_photo,
    AssetKind.scan: _extract_scan,
    AssetKind.pdf: _extract_pdf,
    AssetKind.deck: _extract_deck,
    AssetKind.journal: _extract_text,
    AssetKind.story: _extract_text,
}


@register
class ExtractHandler(Handler):
    type = "extract"

    async def run(self, ctx: JobContext, job: Job) -> dict[str, Any]:
        asset_id = int(job.payload["asset_id"])
        async with ctx.db.sessionmaker() as s:
            asset = await s.get(Asset, asset_id)
            if asset is None:
                return {"skipped": "asset deleted"}
            asset.status, asset.error = AssetStatus.processing, None
            await s.commit()

        data = await ctx.storage.get(asset.storage_key)
        out = await EXTRACTORS[AssetKind(asset.kind)](ctx, asset, data)

        async with ctx.db.sessionmaker() as s:
            asset = await s.get(Asset, asset_id)
            if asset is None:
                return {"skipped": "asset deleted"}
            await self._persist(ctx, s, asset, out)
            ocr_pages = [
                {"page_no": p.page_no, "image_key": p.image_key} for p in out.pages if p.needs_ocr and p.image_key
            ]
            if ocr_pages:
                await ctx.queue.enqueue(
                    s,
                    "ocr",
                    {"asset_id": asset.id, "lang_hint": asset.language, "pages": ocr_pages},
                    asset_id=asset.id,
                    priority=60,
                    dedupe_key=f"ocr:{asset.id}",
                )
            else:
                await enqueue_index(ctx, s, asset.id, priority=70)
            await s.commit()
        return {
            "pages": len(out.pages),
            "ocr_pages": len(ocr_pages),
            "children": len(out.children),
            "near_duplicate_of": out.meta.get("near_duplicate_of"),
        }

    async def _persist(self, ctx: JobContext, s: Any, asset: Asset, out: Extraction) -> None:
        await s.execute(delete(Page).where(Page.asset_id == asset.id))
        for p in out.pages:
            if p.image is not None:
                p.image_key = f"pages/{asset.id}/{p.page_no}.png"
                await ctx.storage.put(p.image_key, p.image, "image/png")
            s.add(
                Page(
                    asset_id=asset.id,
                    page_no=p.page_no,
                    image_key=p.image_key,
                    text=p.text,
                    source=p.source,
                    needs_ocr=p.needs_ocr,
                    language=detect_language(p.text)[0] if p.text else None,
                )
            )
        for key, value in out.updates.items():
            setattr(asset, key, value)
        if out.thumbnail:
            asset.thumb_key = f"thumbs/{asset.id}.webp"
            await ctx.storage.put(asset.thumb_key, out.thumbnail, "image/webp")

        await self._link_site(s, asset)
        if asset.phash and asset.kind == AssetKind.photo:
            dup = await self._near_duplicate(s, asset)
            if dup is not None:
                out.meta["near_duplicate_of"] = dup
                original = await s.get(Asset, dup)
                if asset.site_id is None and original is not None and original.site_id is not None:
                    # e.g. a photo rescued from a slide deck: inherit where its original was taken
                    asset.site_id = original.site_id
                    asset.lat, asset.lon, asset.geo_source = original.lat, original.lon, "site"
                    out.meta["site_link"] = {"method": "near-duplicate", "asset_id": dup}
        asset.meta = {**(asset.meta or {}), **out.meta}

        for img in out.children:
            title = img.caption or f"{asset.title} - slide {img.slide_no}"
            await ingest_bytes(
                s,
                ctx.storage,
                ctx.queue,
                ctx.settings,
                f"slide{img.slide_no}{img.ext}",
                img.data,
                IngestMeta(
                    title=title,
                    kind="photo",
                    site_id=asset.site_id,
                    journey_id=asset.journey_id,
                    parent_id=asset.id,
                    contributor=asset.contributor,
                    license=asset.license,
                    attribution=asset.attribution,
                    context=f"Rescued from deck '{asset.title}', slide {img.slide_no}",
                ),
            )
        await s.flush()

    @staticmethod
    async def _link_site(s: Any, asset: Asset) -> None:
        """Photos geotagged near a known site are attached to it; site-linked assets inherit its location."""
        if asset.site_id is None and asset.lat is not None and asset.lon is not None:
            rows = (await s.execute(select(Site.id, Site.lat, Site.lon))).all()
            hit = nearest(asset.lat, asset.lon, [_SiteRef(*r) for r in rows], SITE_LINK_KM)
            if hit is not None:
                asset.site_id = hit[0].id
                asset.meta = {**(asset.meta or {}), "site_link": {"method": "gps", "distance_km": round(hit[1], 3)}}
        if asset.lat is None and asset.site_id is not None:
            site = await s.get(Site, asset.site_id)
            if site is not None:
                asset.lat, asset.lon, asset.geo_source = site.lat, site.lon, "site"

    @staticmethod
    async def _near_duplicate(s: Any, asset: Asset) -> int | None:
        # A 64-bit dHash compared by Hamming distance; at archive scale this moves to a BK-tree or
        # Postgres `bit_count(phash # $1)` - the interface stays the same.
        if asset.phash is None:
            return None
        phash = asset.phash
        rows = (
            await s.execute(
                select(Asset.id, Asset.phash).where(
                    Asset.kind == AssetKind.photo, Asset.phash.is_not(None), Asset.id != asset.id
                )
            )
        ).all()
        best = min(((hamming(phash, ph), aid) for aid, ph in rows), default=None)
        return best[1] if best is not None and best[0] <= NEAR_DUPLICATE_BITS else None
