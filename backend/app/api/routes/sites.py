from __future__ import annotations

import hashlib
from collections import Counter
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import or_, select

from app.api.deps import ServicesDep, SessionDep
from app.core.errors import AppError, ConflictError, NotFoundError
from app.core.security import require_ingest
from app.db.models import Asset, AssetKind, AssetStatus, Chunk, Journey, JourneyStop, Site, Twin
from app.schemas.catalog import (
    JobOut,
    JourneyRef,
    NearbySite,
    SiteCreate,
    SiteDetail,
    SiteOut,
    TwinOut,
    TwinRequest,
)
from app.services.catalog import cover_url, index_site, site_counts
from app.services.geo import haversine_km
from app.services.search import asset_brief

router = APIRouter(prefix="/sites", tags=["sites"])


def site_out(site: Site, assets: dict[int, int], twins: dict[int, int]) -> SiteOut:
    out = SiteOut.model_validate(site)
    out.cover_url = cover_url(site.cover_asset_id)
    out.asset_count, out.twin_count = assets.get(site.id, 0), twins.get(site.id, 0)
    return out


def twin_out(t: Twin) -> TwinOut:
    out = TwinOut.model_validate(t)
    out.url = f"/api/v1/twins/{t.id}/file"
    return out


async def get_site(session: SessionDep, slug: str) -> Site:
    site = await session.scalar(select(Site).where(Site.slug == slug))
    if site is None:
        raise NotFoundError(f"site {slug!r} not found")
    return site


@router.get("", response_model=list[SiteOut], summary="All heritage sites")
async def list_sites(
    session: SessionDep,
    category: str | None = None,
    state: str | None = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
) -> list[SiteOut]:
    conds: list[Any] = []
    if category:
        conds.append(Site.category == category)
    if state:
        conds.append(Site.state == state)
    if q:
        like = f"%{q.replace('%', '')}%"
        conds.append(or_(Site.name.ilike(like), Site.name_native.ilike(like)))
    rows = (await session.scalars(select(Site).where(*conds).order_by(Site.name))).all()
    assets, twins = await site_counts(session)
    return [site_out(s, assets, twins) for s in rows]


@router.get("/geojson", summary="Sites as GeoJSON points (map layer)")
async def sites_geojson(session: SessionDep) -> dict[str, Any]:
    rows = (await session.scalars(select(Site).order_by(Site.id))).all()
    assets, twins = await site_counts(session)
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "id": s.id,
                "geometry": {"type": "Point", "coordinates": [s.lon, s.lat]},
                "properties": {
                    "id": s.id,
                    "slug": s.slug,
                    "name": s.name,
                    "name_native": s.name_native,
                    "category": s.category,
                    "era_start": s.era_start,
                    "era_label": s.era_label,
                    "unesco": s.unesco,
                    "assets": assets.get(s.id, 0),
                    "twins": twins.get(s.id, 0),
                    "cover_url": cover_url(s.cover_asset_id),
                },
            }
            for s in rows
        ],
    }


@router.post("", response_model=SiteOut, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_ingest)])
async def create_site(services: ServicesDep, session: SessionDep, body: SiteCreate) -> SiteOut:
    if await session.scalar(select(Site.id).where(Site.slug == body.slug)):
        raise ConflictError(f"site {body.slug!r} already exists")
    site = Site(**body.model_dump())
    await index_site(site, services.settings)
    session.add(site)
    await session.commit()
    return site_out(site, {}, {})


@router.get("/{slug}", response_model=SiteDetail)
async def site_detail(session: SessionDep, slug: str) -> SiteDetail:
    site = await get_site(session, slug)
    assets_rows = (
        await session.scalars(
            select(Asset)
            .where(Asset.site_id == site.id)
            .order_by(Asset.kind != AssetKind.photo, Asset.era_year, Asset.id)
        )
    ).all()
    twins = (await session.scalars(select(Twin).where(Twin.site_id == site.id).order_by(Twin.id.desc()))).all()
    journeys = (
        await session.scalars(
            select(Journey).where(Journey.id.in_(select(JourneyStop.journey_id).where(JourneyStop.site_id == site.id)))
        )
    ).all()
    langs = Counter(
        lang
        for (lang,) in (
            await session.execute(
                select(Chunk.language).join(Asset, Asset.id == Chunk.asset_id).where(Asset.site_id == site.id)
            )
        ).all()
        if lang
    )
    others = (await session.scalars(select(Site).where(Site.id != site.id))).all()
    nearby = sorted(
        (
            NearbySite(
                slug=o.slug,
                name=o.name,
                category=o.category,
                distance_km=round(haversine_km(site.lat, site.lon, o.lat, o.lon), 1),
            )
            for o in others
        ),
        key=lambda n: n.distance_km,
    )[:6]
    counts = ({site.id: len(assets_rows)}, {site.id: len(twins)})
    base = site_out(site, *counts)
    return SiteDetail(
        **base.model_dump(),
        alt_names=site.alt_names,
        description=site.description,
        assets=[asset_brief(a, site) for a in assets_rows],
        twins=[twin_out(t) for t in twins],
        journeys=[JourneyRef(slug=j.slug, title=j.title, year=j.year, color=j.color) for j in journeys],
        nearby=nearby,
        languages=dict(langs),
    )


@router.get("/{slug}/twins", response_model=list[TwinOut])
async def site_twins(session: SessionDep, slug: str) -> list[TwinOut]:
    site = await get_site(session, slug)
    rows = (await session.scalars(select(Twin).where(Twin.site_id == site.id).order_by(Twin.id.desc()))).all()
    return [twin_out(t) for t in rows]


@router.post(
    "/{slug}/twins",
    response_model=JobOut,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_ingest)],
    summary="Queue a 3D reconstruction (GPU) from this site's photos",
)
async def request_twin(services: ServicesDep, session: SessionDep, slug: str, body: TwinRequest) -> JobOut:
    site = await get_site(session, slug)
    photos = (
        await session.scalars(
            select(Asset).where(
                Asset.id.in_(body.asset_ids),
                Asset.status == AssetStatus.ready,
                Asset.kind.in_([AssetKind.photo, AssetKind.scan]),
            )
        )
    ).all()
    if not photos:
        raise AppError("none of the given assets are processed photos", status_code=422)
    if body.method == "gaussian-splat" and len(photos) < 8:
        raise AppError("gaussian splatting needs at least 8 overlapping photos", status_code=422)
    payload = {
        "site_id": site.id,
        "method": body.method,
        "title": body.title,
        "images": [{"asset_id": p.id, "image_key": p.storage_key} for p in photos],
    }
    ids = ",".join(str(i) for i in sorted(p.id for p in photos))
    job = await services.queue.enqueue(
        session,
        "reconstruct3d",
        payload,
        site_id=site.id,
        priority=150,
        dedupe_key=f"reconstruct3d:{site.id}:{body.method}:{hashlib.sha1(ids.encode()).hexdigest()[:16]}",
    )
    await session.commit()
    return JobOut.model_validate(job)
