from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from pathlib import PurePath

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import NotFoundError, PayloadTooLargeError
from app.db.models import Asset, AssetKind, AssetStatus, Journey, Site
from app.services.extractors.files import classify_upload
from app.services.jobs import JobQueue
from app.services.storage import Storage

log = logging.getLogger(__name__)

_PRIORITY = {AssetKind.journal: 50, AssetKind.story: 50, AssetKind.scan: 60, AssetKind.pdf: 70, AssetKind.deck: 80}


@dataclass(slots=True)
class IngestMeta:
    title: str | None = None
    kind: str | None = None  # optional hint: "scan" for document photos, "story" for folklore
    site_id: int | None = None
    journey_id: int | None = None
    parent_id: int | None = None
    contributor: str | None = None
    license: str | None = None
    attribution: str | None = None
    source_url: str | None = None
    caption: str | None = None
    language: str | None = None
    lat: float | None = None
    lon: float | None = None
    context: str | None = None  # e.g. slide title the image was rescued from


def _title_from_filename(name: str) -> str:
    stem = PurePath(name).stem.replace("_", " ").replace("-", " ").strip()
    return stem[:1].upper() + stem[1:] if stem else "Untitled"


async def ingest_bytes(
    session: AsyncSession,
    storage: Storage,
    queue: JobQueue,
    settings: Settings,
    filename: str,
    data: bytes,
    meta: IngestMeta,
) -> tuple[Asset, bool]:
    """Store an upload and schedule its processing DAG. Returns (asset, created)."""
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise PayloadTooLargeError(f"{filename} exceeds {settings.max_upload_mb} MB")
    if not data:
        raise PayloadTooLargeError(f"{filename} is empty", status_code=400, title="Empty file")
    kind, mime, ext = classify_upload(filename, data, meta.kind)
    sha = hashlib.sha256(data).hexdigest()

    existing = await session.scalar(select(Asset).where(Asset.sha256 == sha))
    if existing is not None:
        log.info("dedupe: %s already stored as asset %s", filename, existing.id)
        return existing, False

    if meta.site_id is not None and await session.get(Site, meta.site_id) is None:
        raise NotFoundError(f"site {meta.site_id} not found")
    if meta.journey_id is not None and await session.get(Journey, meta.journey_id) is None:
        raise NotFoundError(f"journey {meta.journey_id} not found")

    key = f"originals/{sha[:2]}/{sha}{ext}"
    if not await storage.exists(key):
        await storage.put(key, data, mime)

    asset = Asset(
        kind=kind,
        title=(meta.title or _title_from_filename(filename))[:300],
        original_filename=PurePath(filename).name[:300],
        mime=mime,
        size_bytes=len(data),
        sha256=sha,
        storage_key=key,
        site_id=meta.site_id,
        journey_id=meta.journey_id,
        parent_id=meta.parent_id,
        contributor=meta.contributor,
        license=meta.license,
        attribution=meta.attribution,
        source_url=meta.source_url,
        caption=meta.caption,
        caption_source="contributor" if meta.caption else None,
        language=meta.language,
        lat=meta.lat,
        lon=meta.lon,
        geo_source="manual" if meta.lat is not None and meta.lon is not None else None,
        status=AssetStatus.queued,
        meta={"context": meta.context} if meta.context else {},
    )
    session.add(asset)
    await session.flush()
    await queue.enqueue(
        session,
        "extract",
        {"asset_id": asset.id},
        asset_id=asset.id,
        priority=_PRIORITY.get(kind, 90),
        dedupe_key=f"extract:{asset.id}",
    )
    return asset, True
