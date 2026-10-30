"""Gazetteer-driven named-entity linking for heritage texts.

Every site name (English, native script and alternates) and a curated list of places is compiled
into phonetic token sequences. Text in *any* script is tokenised, reduced to the same phonetic
space and matched with a longest-match-first sliding window, so a Gujarati travel journal that
mentions "અડાલજ" is linked to the Adalaj Stepwell record and pinned on the map.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.core.config import BACKEND_DIR
from app.services.text.dates import DateMention, extract_dates
from app.services.text.phonetic import phonetic_key
from app.services.text.scripts import WORD_RE as _TOKEN

MAX_NGRAM = 6
PLACES_FILE = BACKEND_DIR / "data" / "gazetteer" / "places.json"


@dataclass(frozen=True, slots=True)
class GazetteerEntry:
    kind: str  # site | place
    name: str
    key: tuple[str, ...]
    lat: float
    lon: float
    site_id: int | None = None


@dataclass(frozen=True, slots=True)
class Mention:
    kind: str  # site | place | date
    surface: str
    normalized: str
    start: int
    end: int
    site_id: int | None = None
    lat: float | None = None
    lon: float | None = None
    year: int | None = None


def _key(name: str) -> tuple[str, ...]:
    return tuple(phonetic_key(name).split())


class Gazetteer:
    def __init__(self, entries: list[GazetteerEntry]) -> None:
        self._index: dict[tuple[str, ...], GazetteerEntry] = {}
        for e in entries:
            if not e.key:
                continue
            if len(e.key) == 1 and len(e.key[0]) < 4:
                continue  # too ambiguous ("vav", "ki")
            existing = self._index.get(e.key)
            if existing is None or (existing.kind == "place" and e.kind == "site"):
                self._index[e.key] = e  # sites win over generic places

    def __len__(self) -> int:
        return len(self._index)

    def find(self, text: str) -> list[Mention]:
        tokens: list[tuple[str, int, int]] = []
        for m in _TOKEN.finditer(text):
            key = phonetic_key(m.group())
            for part in key.split():
                tokens.append((part, m.start(), m.end()))
        out: list[Mention] = []
        i = 0
        while i < len(tokens):
            matched = False
            for n in range(min(MAX_NGRAM, len(tokens) - i), 0, -1):
                ngram = tuple(t[0] for t in tokens[i : i + n])
                entry = self._index.get(ngram)
                if entry is not None:
                    start, end = tokens[i][1], tokens[i + n - 1][2]
                    out.append(
                        Mention(
                            kind=entry.kind,
                            surface=text[start:end],
                            normalized=entry.name,
                            start=start,
                            end=end,
                            site_id=entry.site_id,
                            lat=entry.lat,
                            lon=entry.lon,
                        )
                    )
                    i += n
                    matched = True
                    break
            if not matched:
                i += 1
        return out


@lru_cache(maxsize=1)
def static_places(path: Path = PLACES_FILE) -> tuple[GazetteerEntry, ...]:
    if not path.exists():
        return ()
    rows = json.loads(path.read_text(encoding="utf-8"))
    out: list[GazetteerEntry] = []
    for row in rows:
        for name in [row["name"], *row.get("alt", [])]:
            out.append(GazetteerEntry("place", row["name"], _key(name), row["lat"], row["lon"]))
    return tuple(out)


def build_gazetteer(sites: list[tuple[int, str, list[str], float, float]]) -> Gazetteer:
    """sites: (id, canonical name, all names, lat, lon)."""
    entries = list(static_places())
    for site_id, canonical, names, lat, lon in sites:
        for name in names:
            entries.append(GazetteerEntry("site", canonical, _key(name), lat, lon, site_id))
    return Gazetteer(entries)


def extract_entities(text: str, gazetteer: Gazetteer) -> list[Mention]:
    mentions = gazetteer.find(text)
    for d in extract_dates(text):
        mentions.append(_date_mention(d))
    return sorted(mentions, key=lambda m: m.start)


def _date_mention(d: DateMention) -> Mention:
    from app.services.text.dates import format_year

    return Mention("date", d.surface, f"{format_year(d.year)} ({d.calendar})", d.start, d.end, year=d.year)
