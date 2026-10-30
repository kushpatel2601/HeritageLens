"""Response models for hybrid search."""

from __future__ import annotations

from pydantic import BaseModel, Field


class Snippet(BaseModel):
    text: str
    highlights: list[tuple[int, int]] = Field(default_factory=list, description="[start, end) offsets into text")
    prefix_ellipsis: bool = False
    suffix_ellipsis: bool = False


class AssetBrief(BaseModel):
    id: int
    kind: str
    title: str
    status: str
    thumb_url: str | None = None
    language: str | None = None
    site_id: int | None = None
    site_name: str | None = None
    site_slug: str | None = None
    era_year: int | None = None
    lat: float | None = None
    lon: float | None = None


class SearchHit(BaseModel):
    chunk_id: int
    page_no: int
    score: float = Field(description="RRF score normalised to [0, 1]")
    matched_by: list[str] = Field(description="semantic | keyword | phonetic")
    language: str | None
    snippet: Snippet
    translation: Snippet | None = None
    translation_engine: str | None = None
    more_in_asset: int = 0
    asset: AssetBrief


class SiteHit(BaseModel):
    id: int
    slug: str
    name: str
    name_native: str | None
    category: str
    lat: float
    lon: float
    score: float
    reason: str


class PhotoHit(BaseModel):
    score: float
    asset: AssetBrief


class QueryInterpretation(BaseModel):
    script: str | None
    language: str | None
    phonetic: str
    terms: list[str]


class SearchResponse(BaseModel):
    query: str
    interpreted: QueryInterpretation
    total: int
    hits: list[SearchHit]
    sites: list[SiteHit]
    photos: list[PhotoHit]
    facets: dict[str, dict[str, int]]
    suggestions: list[str]
    took_ms: float
    backend: str
    embedder: str
