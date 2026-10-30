"""Read models for the public catalogue API."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.search import AssetBrief

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


# ---------------------------------------------------------------- sites
class SiteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str
    name: str
    name_native: str | None
    category: str
    state: str | None
    district: str | None
    lat: float
    lon: float
    era_start: int | None
    era_end: int | None
    era_label: str | None
    summary: str
    tags: list[str]
    unesco: bool
    cover_url: str | None = None
    asset_count: int = 0
    twin_count: int = 0


class NearbySite(BaseModel):
    slug: str
    name: str
    category: str
    distance_km: float


class JourneyRef(BaseModel):
    slug: str
    title: str
    year: int
    color: str


class TwinOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    site_id: int
    title: str
    method: str
    format: str
    point_count: int | None
    source_asset_ids: list[int]
    meta: dict[str, Any]
    created_at: datetime
    url: str = ""


class SiteDetail(SiteOut):
    alt_names: list[str]
    description: str | None
    assets: list[AssetBrief]
    twins: list[TwinOut]
    journeys: list[JourneyRef]
    nearby: list[NearbySite]
    languages: dict[str, int]


class SiteCreate(BaseModel):
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,118}$")
    name: str = Field(min_length=2, max_length=200)
    name_native: str | None = Field(default=None, max_length=200)
    alt_names: list[str] = Field(default_factory=list, max_length=20)
    category: Literal[
        "stepwell", "fort", "temple", "mosque", "palace", "archaeological", "craft", "landscape", "other"
    ] = "other"
    state: str | None = None
    district: str | None = None
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    era_start: int | None = None
    era_end: int | None = None
    era_label: str | None = None
    summary: str = Field(default="", max_length=2000)
    description: str | None = Field(default=None, max_length=20_000)
    tags: list[str] = Field(default_factory=list, max_length=20)
    unesco: bool = False


# ---------------------------------------------------------------- journeys
class JourneyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str
    title: str
    fellow: str
    year: int
    region: str | None
    summary: str
    color: str
    cover_url: str | None = None
    stop_count: int = 0
    distance_km: float = 0.0
    bbox: tuple[float, float, float, float] | None = None


class StopOut(BaseModel):
    seq: int
    title: str
    lat: float
    lon: float
    visited_on: date | None
    narrative: str
    leg_km: float
    site: SiteOut | None
    assets: list[AssetBrief]


class JourneyDetail(JourneyOut):
    stops: list[StopOut]
    route: dict[str, Any]  # GeoJSON Feature<LineString>


# ---------------------------------------------------------------- assets & documents
class PageOut(BaseModel):
    page_no: int
    image_url: str | None
    source: str
    needs_ocr: bool
    ocr_engine: str | None
    ocr_confidence: float | None
    language: str | None
    chars: int


class EntityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    chunk_id: int
    kind: str
    surface: str
    normalized: str
    site_id: int | None
    lat: float | None
    lon: float | None
    year: int | None
    start: int
    end: int


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    type: str
    queue: str
    status: str
    priority: int
    attempts: int
    max_attempts: int
    asset_id: int | None
    site_id: int | None
    error: str | None
    result: dict[str, Any] | None
    lease_owner: str | None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    asset_title: str | None = Field(default=None, description="Filled by the /jobs endpoints only")
    site_name: str | None = Field(default=None, description="Filled by the /jobs endpoints only")
    site_slug: str | None = Field(default=None, description="Filled by the /jobs endpoints only")


class AssetDetail(AssetBrief):
    original_filename: str
    mime: str
    size_bytes: int
    width: int | None
    height: int | None
    geo_source: str | None
    captured_at: datetime | None
    journey_id: int | None
    journey_slug: str | None = None
    parent_id: int | None
    contributor: str | None
    license: str | None
    attribution: str | None
    source_url: str | None
    caption: str | None
    caption_source: str | None
    error: str | None
    created_at: datetime
    original_url: str
    pages: list[PageOut]
    entities: list[EntityOut]
    jobs: list[JobOut]
    children: list[AssetBrief]
    near_duplicate_of: int | None = None
    translated_ratio: float = 0.0


class ChunkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    page_no: int
    seq: int
    char_start: int
    text: str
    language: str | None
    script: str | None
    translation: str | None
    translation_engine: str | None


class AssetUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    site_id: int | None = None
    journey_id: int | None = None
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)
    caption: str | None = Field(default=None, max_length=1000)
    contributor: str | None = Field(default=None, max_length=120)


class UploadResult(BaseModel):
    asset: AssetBrief
    created: bool
    job_ids: list[int]


# ---------------------------------------------------------------- ops
class TwinRequest(BaseModel):
    asset_ids: list[int] = Field(min_length=1, max_length=200)
    method: Literal["depth-relief", "gaussian-splat"] = "depth-relief"
    title: str | None = Field(default=None, max_length=200)


class Stats(BaseModel):
    sites: int
    journeys: int
    assets: int
    assets_by_kind: dict[str, int]
    assets_by_status: dict[str, int]
    pages: int
    ocr_pages: int
    chunks: int
    translated_chunks: int
    languages: dict[str, int]
    entities: int
    geotagged_assets: int
    twins: int
    jobs_by_status: dict[str, int]
    queue_depth: dict[str, int]
    workers_online: int
    embedder: str
    database: str


class Health(BaseModel):
    status: Literal["ok", "degraded"]
    version: str
    database: str
    embedder: str
    workers_online: dict[str, int]
    checks: dict[str, str]
