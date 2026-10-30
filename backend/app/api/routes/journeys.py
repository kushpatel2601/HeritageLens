from __future__ import annotations

from collections import defaultdict
from typing import Any

from fastapi import APIRouter
from sqlalchemy import or_, select

from app.api.deps import SessionDep
from app.api.routes.sites import site_out
from app.core.errors import NotFoundError
from app.db.models import Asset, AssetStatus, Journey, JourneyStop, Site
from app.schemas.catalog import JourneyDetail, JourneyOut, StopOut
from app.schemas.search import AssetBrief
from app.services.catalog import cover_url, route_feature, site_counts, stops_geometry
from app.services.geo import haversine_km
from app.services.search import asset_brief

router = APIRouter(prefix="/journeys", tags=["journeys"])

STOP_ASSETS = 8
ATTACH_KM = 25.0


async def _stops(session: SessionDep, journey_ids: list[int]) -> dict[int, list[JourneyStop]]:
    rows = (
        await session.scalars(
            select(JourneyStop)
            .where(JourneyStop.journey_id.in_(journey_ids))
            .order_by(JourneyStop.journey_id, JourneyStop.seq)
        )
    ).all()
    out: dict[int, list[JourneyStop]] = defaultdict(list)
    for r in rows:
        out[r.journey_id].append(r)
    return out


def journey_out(j: Journey, stops: list[JourneyStop]) -> JourneyOut:
    out = JourneyOut.model_validate(j)
    _, out.distance_km, out.bbox = stops_geometry(stops)
    out.stop_count, out.cover_url = len(stops), cover_url(j.cover_asset_id)
    return out


@router.get("", response_model=list[JourneyOut], summary="Fellowship expeditions")
async def list_journeys(session: SessionDep) -> list[JourneyOut]:
    rows = (await session.scalars(select(Journey).order_by(Journey.year.desc(), Journey.title))).all()
    stops = await _stops(session, [j.id for j in rows])
    return [journey_out(j, stops[j.id]) for j in rows]


@router.get("/geojson", summary="All expedition routes as GeoJSON LineStrings (map layer)")
async def journeys_geojson(session: SessionDep) -> dict[str, Any]:
    rows = (await session.scalars(select(Journey).order_by(Journey.id))).all()
    stops = await _stops(session, [j.id for j in rows])
    return {
        "type": "FeatureCollection",
        "features": [route_feature(j, stops[j.id]) for j in rows if len(stops[j.id]) > 1],
    }


@router.get("/{slug}", response_model=JourneyDetail, summary="Story-mode payload: ordered stops, route and materials")
async def journey_detail(session: SessionDep, slug: str) -> JourneyDetail:
    journey = await session.scalar(select(Journey).where(Journey.slug == slug))
    if journey is None:
        raise NotFoundError(f"journey {slug!r} not found")
    stops = (await _stops(session, [journey.id]))[journey.id]
    legs, _, _ = stops_geometry(stops)
    site_ids = [s.site_id for s in stops if s.site_id]
    sites = {s.id: s for s in (await session.scalars(select(Site).where(Site.id.in_(site_ids)))).all()}
    assets = (
        await session.scalars(
            select(Asset)
            .where(
                Asset.status == AssetStatus.ready,
                Asset.parent_id.is_(None),
                or_(Asset.journey_id == journey.id, Asset.site_id.in_(site_ids)),
            )
            .order_by((Asset.journey_id == journey.id).desc(), Asset.id)
        )
    ).all()

    per_stop: dict[int, list[AssetBrief]] = defaultdict(list)
    stop_by_site = {s.site_id: s.seq for s in stops if s.site_id}
    for a in assets:
        seq = stop_by_site.get(a.site_id) if a.site_id else None
        if seq is None and a.journey_id == journey.id and a.lat is not None and a.lon is not None and stops:
            d, nearest = min((haversine_km(a.lat, a.lon, s.lat, s.lon), s.seq) for s in stops)
            seq = nearest if d <= ATTACH_KM else None
        if seq is not None and len(per_stop[seq]) < STOP_ASSETS:
            per_stop[seq].append(asset_brief(a, sites.get(a.site_id) if a.site_id else None))

    counts = await site_counts(session)
    base = journey_out(journey, stops)
    return JourneyDetail(
        **base.model_dump(),
        stops=[
            StopOut(
                seq=s.seq,
                title=s.title,
                lat=s.lat,
                lon=s.lon,
                visited_on=s.visited_on,
                narrative=s.narrative,
                leg_km=legs[i],
                site=site_out(sites[s.site_id], *counts) if s.site_id in sites else None,
                assets=per_stop[s.seq],
            )
            for i, s in enumerate(stops)
        ],
        route=route_feature(journey, stops),
    )
