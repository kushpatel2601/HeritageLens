from __future__ import annotations

import math
from collections.abc import Iterable
from typing import Protocol, TypeVar

EARTH_KM = 6371.0088


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_KM * math.asin(math.sqrt(a))


class HasLatLon(Protocol):
    lat: float
    lon: float


T = TypeVar("T", bound=HasLatLon)


def nearest(lat: float, lon: float, items: Iterable[T], max_km: float) -> tuple[T, float] | None:
    best: tuple[T, float] | None = None
    for it in items:
        d = haversine_km(lat, lon, it.lat, it.lon)
        if d <= max_km and (best is None or d < best[1]):
            best = (it, d)
    return best


def bbox_contains(bbox: tuple[float, float, float, float], lat: float | None, lon: float | None) -> bool:
    if lat is None or lon is None:
        return False
    west, south, east, north = bbox
    return south <= lat <= north and west <= lon <= east
