from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, File, Form, Query, Request, Response, UploadFile, status
from sqlalchemy import ColumnElement, func, select

from app.api.deps import ServicesDep, SessionDep
from app.api.files import blob_response, guess_type
from app.core.errors import AppError, NotFoundError, PayloadTooLargeError
from app.core.security import require_ingest
from app.db.models import Asset, AssetStatus, Chunk, Entity, Job, Journey, Page, Site
from app.schemas.catalog import (
    AssetDetail,
    AssetUpdate,
    ChunkOut,
    EntityOut,
    JobOut,
    PageOut,
    UploadResult,
)
from app.schemas.catalog import Page as PageOf
from app.schemas.search import AssetBrief
from app.services.ingest import IngestMeta, ingest_bytes
from app.services.pipeline import enqueue_index
from app.services.search import asset_brief

router = APIRouter(prefix="/assets", tags=["assets"])

Kind = Literal["photo", "scan", "pdf", "deck", "journal", "story"]
MAX_FILES = 50


async def _get(session: SessionDep, asset_id: int) -> Asset:
    asset = await session.get(Asset, asset_id)
    if asset is None:
        raise NotFoundError(f"asset {asset_id} not found")
    return asset


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=list[UploadResult],
    dependencies=[Depends(require_ingest)],
    summary="Upload one or more files (photos, scans, PDFs, PPTX decks, journals, stories)",
)
async def upload(
    services: ServicesDep,
    session: SessionDep,
    files: Annotated[list[UploadFile], File(description="Up to 50 files per request")],
    kind: Annotated[Kind | None, Form()] = None,
    title: Annotated[str | None, Form(max_length=300)] = None,
    site_id: Annotated[int | None, Form()] = None,
    journey_id: Annotated[int | None, Form()] = None,
    contributor: Annotated[str | None, Form(max_length=120)] = None,
    license: Annotated[str | None, Form(max_length=80)] = None,
    caption: Annotated[str | None, Form(max_length=1000)] = None,
    language: Annotated[str | None, Form(max_length=8)] = None,
    lat: Annotated[float | None, Form(ge=-90, le=90)] = None,
    lon: Annotated[float | None, Form(ge=-180, le=180)] = None,
) -> list[UploadResult]:
    if len(files) > MAX_FILES:
        raise PayloadTooLargeError(f"at most {MAX_FILES} files per request")
    limit = services.settings.max_upload_mb * 1024 * 1024
    out: list[UploadResult] = []
    for f in files:
        data = await f.read(limit + 1)
        meta = IngestMeta(
            title=title if len(files) == 1 else None,
            kind=kind,
            site_id=site_id,
            journey_id=journey_id,
            contributor=contributor,
            license=license,
            caption=caption,
            language=language,
            lat=lat,
            lon=lon,
        )
        asset, created = await ingest_bytes(
            session, services.storage, services.queue, services.settings, f.filename or "upload", data, meta
        )
        await session.commit()
        job_ids = list(
            (await session.scalars(select(Job.id).where(Job.asset_id == asset.id, Job.type == "extract"))).all()
        )
        site = await session.get(Site, asset.site_id) if asset.site_id else None
        out.append(UploadResult(asset=asset_brief(asset, site), created=created, job_ids=job_ids))
    return out


@router.get("", response_model=PageOf[AssetBrief], summary="Browse the archive")
async def list_assets(
    session: SessionDep,
    kind: Annotated[list[Kind] | None, Query()] = None,
    status_: Annotated[Literal["queued", "processing", "ready", "failed"] | None, Query(alias="status")] = None,
    site_id: int | None = None,
    journey_id: int | None = None,
    language: str | None = None,
    has_geo: bool | None = None,
    q: Annotated[str | None, Query(max_length=200, description="Title contains")] = None,
    sort: Literal["recent", "title", "era"] = "recent",
    include_children: bool = True,
    limit: Annotated[int, Query(ge=1, le=200)] = 48,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PageOf[AssetBrief]:
    conds: list[ColumnElement[bool]] = []
    if kind:
        conds.append(Asset.kind.in_(kind))
    if status_:
        conds.append(Asset.status == status_)
    if site_id is not None:
        conds.append(Asset.site_id == site_id)
    if journey_id is not None:
        conds.append(Asset.journey_id == journey_id)
    if language:
        conds.append(Asset.language == language)
    if has_geo is not None:
        conds.append(Asset.lat.is_not(None) if has_geo else Asset.lat.is_(None))
    if q:
        conds.append(Asset.title.ilike(f"%{q.replace('%', '').replace('_', '')}%"))
    if not include_children:
        conds.append(Asset.parent_id.is_(None))
    total = await session.scalar(select(func.count(Asset.id)).where(*conds)) or 0
    order: dict[str, list[Any]] = {
        "recent": [Asset.created_at.desc(), Asset.id.desc()],
        "title": [Asset.title, Asset.id],
        "era": [Asset.era_year.is_(None), Asset.era_year, Asset.id],
    }
    rows = (
        await session.execute(
            select(Asset, Site)
            .outerjoin(Site, Site.id == Asset.site_id)
            .where(*conds)
            .order_by(*order[sort])
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return PageOf[AssetBrief](items=[asset_brief(a, s) for a, s in rows], total=total, limit=limit, offset=offset)


@router.get("/geojson", summary="Geotagged assets as a GeoJSON FeatureCollection (map layer)")
async def assets_geojson(session: SessionDep, limit: Annotated[int, Query(ge=1, le=20000)] = 5000) -> dict[str, object]:
    rows = (
        await session.execute(
            select(
                Asset.id,
                Asset.kind,
                Asset.title,
                Asset.lat,
                Asset.lon,
                Asset.thumb_key,
                Asset.site_id,
                Asset.geo_source,
            )
            .where(Asset.lat.is_not(None), Asset.status == AssetStatus.ready)
            .order_by(Asset.id.desc())
            .limit(limit)
        )
    ).all()
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "id": r.id,
                "geometry": {"type": "Point", "coordinates": [r.lon, r.lat]},
                "properties": {
                    "id": r.id,
                    "kind": r.kind,
                    "title": r.title,
                    "site_id": r.site_id,
                    "geo_source": r.geo_source,
                    "thumb_url": f"/api/v1/assets/{r.id}/thumbnail" if r.thumb_key else None,
                },
            }
            for r in rows
        ],
    }


@router.get("/{asset_id}", response_model=AssetDetail)
async def get_asset(session: SessionDep, asset_id: int) -> AssetDetail:
    asset = await _get(session, asset_id)
    site = await session.get(Site, asset.site_id) if asset.site_id else None
    journey = await session.get(Journey, asset.journey_id) if asset.journey_id else None
    pages = (await session.scalars(select(Page).where(Page.asset_id == asset_id).order_by(Page.page_no))).all()
    entities = (await session.scalars(select(Entity).where(Entity.asset_id == asset_id).order_by(Entity.id))).all()
    jobs = (await session.scalars(select(Job).where(Job.asset_id == asset_id).order_by(Job.id))).all()
    children = (
        await session.execute(
            select(Asset, Site)
            .outerjoin(Site, Site.id == Asset.site_id)
            .where(Asset.parent_id == asset_id)
            .order_by(Asset.id)
        )
    ).all()
    n_chunks, n_translated = (
        await session.execute(
            select(func.count(Chunk.id), func.count(Chunk.translation)).where(Chunk.asset_id == asset_id)
        )
    ).one()
    non_en = await session.scalar(
        select(func.count(Chunk.id)).where(
            Chunk.asset_id == asset_id, Chunk.language.is_not(None), Chunk.language != "en"
        )
    )
    brief = asset_brief(asset, site)
    return AssetDetail(
        **brief.model_dump(),
        original_filename=asset.original_filename,
        mime=asset.mime,
        size_bytes=asset.size_bytes,
        width=asset.width,
        height=asset.height,
        geo_source=asset.geo_source,
        captured_at=asset.captured_at,
        journey_id=asset.journey_id,
        journey_slug=journey.slug if journey else None,
        parent_id=asset.parent_id,
        contributor=asset.contributor,
        license=asset.license,
        attribution=asset.attribution,
        source_url=asset.source_url,
        caption=asset.caption,
        caption_source=asset.caption_source,
        error=asset.error,
        created_at=asset.created_at,
        original_url=f"/api/v1/assets/{asset.id}/original",
        pages=[
            PageOut(
                page_no=p.page_no,
                image_url=f"/api/v1/assets/{asset.id}/pages/{p.page_no}/image" if p.image_key else None,
                source=p.source,
                needs_ocr=p.needs_ocr,
                ocr_engine=p.ocr_engine,
                ocr_confidence=p.ocr_confidence,
                language=p.language,
                chars=len(p.text),
            )
            for p in pages
        ],
        entities=[EntityOut.model_validate(e) for e in entities],
        jobs=[JobOut.model_validate(j) for j in jobs],
        children=[asset_brief(a, s) for a, s in children],
        near_duplicate_of=(asset.meta or {}).get("near_duplicate_of"),
        translated_ratio=round(n_translated / non_en, 3) if non_en else (1.0 if n_chunks else 0.0),
    )


@router.patch(
    "/{asset_id}",
    response_model=AssetDetail,
    dependencies=[Depends(require_ingest)],
    summary="Curator corrections (site link, location, caption...) - triggers re-indexing",
)
async def update_asset(services: ServicesDep, session: SessionDep, asset_id: int, body: AssetUpdate) -> AssetDetail:
    asset = await _get(session, asset_id)
    patch = body.model_dump(exclude_unset=True)
    if ("lat" in patch) != ("lon" in patch) or (patch.get("lat") is None) != (patch.get("lon") is None):
        raise AppError("lat and lon must be provided together", status_code=422, title="Invalid location")
    if patch.get("site_id") is not None and await session.get(Site, patch["site_id"]) is None:
        raise NotFoundError(f"site {patch['site_id']} not found")
    if patch.get("journey_id") is not None and await session.get(Journey, patch["journey_id"]) is None:
        raise NotFoundError(f"journey {patch['journey_id']} not found")
    for field, value in patch.items():
        setattr(asset, field, value)
    if "lat" in patch:
        asset.geo_source = "manual" if patch["lat"] is not None else None
    if "caption" in patch:
        asset.caption_source = "curator" if patch["caption"] else None
    if "site_id" in patch:
        asset.meta = {**(asset.meta or {}), "site_link": {"method": "curator"}}
    if asset.status == AssetStatus.ready:
        await enqueue_index(services.ctx, session, asset.id, priority=40)
    await session.commit()
    return await get_asset(session, asset_id)


@router.post("/{asset_id}/reprocess", response_model=JobOut, dependencies=[Depends(require_ingest)])
async def reprocess(services: ServicesDep, session: SessionDep, asset_id: int) -> JobOut:
    asset = await _get(session, asset_id)
    asset.status, asset.error = AssetStatus.queued, None
    job = await services.queue.enqueue(
        session, "extract", {"asset_id": asset.id}, asset_id=asset.id, priority=40, dedupe_key=f"extract:{asset.id}"
    )
    await session.commit()
    return JobOut.model_validate(job)


@router.get("/{asset_id}/chunks", response_model=list[ChunkOut], summary="Indexed passages with translations")
async def chunks(session: SessionDep, asset_id: int) -> list[ChunkOut]:
    await _get(session, asset_id)
    rows = (
        await session.scalars(select(Chunk).where(Chunk.asset_id == asset_id).order_by(Chunk.page_no, Chunk.seq))
    ).all()
    return [ChunkOut.model_validate(c) for c in rows]


@router.get("/{asset_id}/pages/{page_no}/text", summary="Full text of one page")
async def page_text(session: SessionDep, asset_id: int, page_no: int) -> dict[str, object]:
    page = await session.scalar(select(Page).where(Page.asset_id == asset_id, Page.page_no == page_no))
    if page is None:
        raise NotFoundError(f"page {page_no} of asset {asset_id} not found")
    return {"page_no": page.page_no, "text": page.text, "source": page.source, "language": page.language}


@router.get("/{asset_id}/original", response_class=Response, summary="Original file as uploaded")
async def original(request: Request, services: ServicesDep, session: SessionDep, asset_id: int) -> Response:
    asset = await _get(session, asset_id)
    return await blob_response(
        request,
        services.storage,
        asset.storage_key,
        media_type=asset.mime,
        etag=asset.sha256,
        immutable=True,
        filename=asset.original_filename,
    )


@router.get("/{asset_id}/thumbnail", response_class=Response)
async def thumbnail(request: Request, services: ServicesDep, session: SessionDep, asset_id: int) -> Response:
    asset = await _get(session, asset_id)
    return await blob_response(
        request,
        services.storage,
        asset.thumb_key,
        media_type="image/webp",
        etag=f"{asset.sha256[:16]}-t{int(asset.updated_at.timestamp())}",
    )


@router.get("/{asset_id}/pages/{page_no}/image", response_class=Response)
async def page_image(
    request: Request, services: ServicesDep, session: SessionDep, asset_id: int, page_no: int
) -> Response:
    page = await session.scalar(select(Page).where(Page.asset_id == asset_id, Page.page_no == page_no))
    if page is None:
        raise NotFoundError(f"page {page_no} of asset {asset_id} not found")
    return await blob_response(request, services.storage, page.image_key, media_type=guess_type(page.image_key or ""))
