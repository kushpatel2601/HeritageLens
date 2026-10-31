"""Catalogue helpers shared by the API and the seeder."""

from __future__ import annotations

import asyncio
from itertools import pairwise
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.models import Asset, Journey, JourneyStop, Site, Twin
from app.services.embeddings import aget_text_embedder
from app.services.geo import haversine_km
from app.services.text.phonetic import phonetic_key


def site_names(site: Site) -> list[str]:
    return [n for n in dict.fromkeys([site.name, site.name_native or "", *(site.alt_names or [])]) if n]


def site_document(site: Site) -> str:
    """Text used for the site's semantic embedding."""
    parts = [*site_names(site), site.category, site.era_label or "", site.state or "", site.summary, *site.tags]
    return ". ".join(p for p in parts if p)


async def index_site(site: Site, settings: Settings) -> None:
    """(Re)compute the site's phonetic name keys and semantic embedding. Caller commits."""
    site.phonetic = " | ".join(dict.fromkeys(k for k in (phonetic_key(n) for n in site_names(site)) if k))
    embedder = await aget_text_embedder(settings)
    site.embedding = (await asyncio.to_thread(embedder.embed, [site_document(site)]))[0]


async def site_counts(session: AsyncSession) -> tuple[dict[int, int], dict[int, int]]:
    assets = dict(
        (
            await session.execute(
                select(Asset.site_id, func.count()).where(Asset.site_id.is_not(None)).group_by(Asset.site_id)
            )
        ).all()
    )
    twins = dict((await session.execute(select(Twin.site_id, func.count()).group_by(Twin.site_id))).all())
    return assets, twins  # type: ignore[return-value]


def cover_url(asset_id: int | None) -> str | None:
    return f"/api/v1/assets/{asset_id}/thumbnail" if asset_id else None


def stops_geometry(stops: list[JourneyStop]) -> tuple[list[float], float, tuple[float, float, float, float] | None]:
    legs = [0.0]
    for a, b in pairwise(stops):
        legs.append(round(haversine_km(a.lat, a.lon, b.lat, b.lon), 2))
    if not stops:
        return legs, 0.0, None
    lons, lats = [s.lon for s in stops], [s.lat for s in stops]
    return legs, round(sum(legs), 1), (min(lons), min(lats), max(lons), max(lats))


def route_feature(journey: Journey, stops: list[JourneyStop]) -> dict[str, Any]:
    return {
        "type": "Feature",
        "properties": {"slug": journey.slug, "title": journey.title, "color": journey.color, "year": journey.year},
        "geometry": {"type": "LineString", "coordinates": [[s.lon, s.lat] for s in stops]},
    }
