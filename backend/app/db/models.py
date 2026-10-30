from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Any

import numpy as np
from sqlalchemy import (
    Boolean,
    Date,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.config import get_settings
from app.db.base import Base, JSONType, TimestampMixin, UTCDateTime, Vector, utcnow

_settings = get_settings()
TEXT_DIM = _settings.embed_dim
IMAGE_DIM = _settings.image_embed_dim


# Lexical document for a chunk: original text + English translation + phonetic (Latin) key, so a query in any
# script or spelling can match. The GIN index on `chunks` is built from this same expression, which is what lets
# the planner use it for the `@@` queries in `services.search`.
def chunk_fts_sql(qualifier: str = "") -> str:
    p = f"{qualifier}." if qualifier else ""
    return (
        f"to_tsvector('simple'::regconfig, coalesce({p}text, '') || ' ' || coalesce({p}translation, '') "
        f"|| ' ' || coalesce({p}phonetic, ''))"
    )


def hnsw_cosine_index(name: str, column: str) -> Index:
    """Approximate-nearest-neighbour index for pgvector `<=>` (cosine distance). PostgreSQL only."""
    return Index(
        name,
        column,
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={column: "vector_cosine_ops"},
    ).ddl_if(dialect="postgresql")


class SiteCategory(StrEnum):
    stepwell = "stepwell"
    fort = "fort"
    temple = "temple"
    mosque = "mosque"
    palace = "palace"
    archaeological = "archaeological"
    craft = "craft"
    landscape = "landscape"
    other = "other"


class AssetKind(StrEnum):
    photo = "photo"
    scan = "scan"  # photographed / scanned document page that needs OCR
    pdf = "pdf"
    deck = "deck"  # PowerPoint presentation
    journal = "journal"  # field notes / travel journals (txt, md, docx)
    story = "story"  # folklore & oral histories


class AssetStatus(StrEnum):
    queued = "queued"
    processing = "processing"
    ready = "ready"
    failed = "failed"


class JobStatus(StrEnum):
    queued = "queued"
    leased = "leased"
    succeeded = "succeeded"
    failed = "failed"  # will be retried
    dead = "dead"  # exhausted retries


class Site(TimestampMixin, Base):
    __tablename__ = "sites"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    name_native: Mapped[str | None] = mapped_column(String(200))
    alt_names: Mapped[list[str]] = mapped_column(JSONType, default=list)
    category: Mapped[str] = mapped_column(String(32), index=True)
    state: Mapped[str | None] = mapped_column(String(80), index=True)
    district: Mapped[str | None] = mapped_column(String(80))
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    era_start: Mapped[int | None] = mapped_column(Integer, index=True)
    era_end: Mapped[int | None] = mapped_column(Integer)
    era_label: Mapped[str | None] = mapped_column(String(120))
    summary: Mapped[str] = mapped_column(Text, default="")
    description: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[list[str]] = mapped_column(JSONType, default=list)
    unesco: Mapped[bool] = mapped_column(Boolean, default=False)
    phonetic: Mapped[str] = mapped_column(Text, default="")
    cover_asset_id: Mapped[int | None] = mapped_column(Integer)  # soft reference (avoids FK cycle)
    embedding: Mapped[np.ndarray | None] = mapped_column(Vector(TEXT_DIM))

    assets: Mapped[list[Asset]] = relationship(back_populates="site", foreign_keys="Asset.site_id")
    twins: Mapped[list[Twin]] = relationship(back_populates="site", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_sites_lat_lon", "lat", "lon"),
        hnsw_cosine_index("ix_sites_embedding_hnsw", "embedding"),
    )


class Journey(TimestampMixin, Base):
    """An Explorer-Fellowship expedition: an ordered route through sites."""

    __tablename__ = "journeys"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(200))
    fellow: Mapped[str] = mapped_column(String(120))
    year: Mapped[int] = mapped_column(Integer, index=True)
    region: Mapped[str | None] = mapped_column(String(120))
    summary: Mapped[str] = mapped_column(Text, default="")
    color: Mapped[str] = mapped_column(String(16), default="#9A3412")
    cover_asset_id: Mapped[int | None] = mapped_column(Integer)

    stops: Mapped[list[JourneyStop]] = relationship(
        back_populates="journey", cascade="all, delete-orphan", order_by="JourneyStop.seq"
    )


class JourneyStop(Base):
    __tablename__ = "journey_stops"

    id: Mapped[int] = mapped_column(primary_key=True)
    journey_id: Mapped[int] = mapped_column(ForeignKey("journeys.id", ondelete="CASCADE"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    site_id: Mapped[int | None] = mapped_column(ForeignKey("sites.id", ondelete="SET NULL"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    visited_on: Mapped[date | None] = mapped_column(Date)
    narrative: Mapped[str] = mapped_column(Text, default="")

    journey: Mapped[Journey] = relationship(back_populates="stops")
    site: Mapped[Site | None] = relationship()

    __table_args__ = (UniqueConstraint("journey_id", "seq", name="uq_journey_stops_journey_seq"),)


class Asset(TimestampMixin, Base):
    __tablename__ = "assets"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(16), index=True)
    title: Mapped[str] = mapped_column(String(300))
    original_filename: Mapped[str] = mapped_column(String(300))
    mime: Mapped[str] = mapped_column(String(120))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    storage_key: Mapped[str] = mapped_column(String(200))
    thumb_key: Mapped[str | None] = mapped_column(String(200))
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    phash: Mapped[str | None] = mapped_column(String(16), index=True)
    lat: Mapped[float | None] = mapped_column(Float)
    lon: Mapped[float | None] = mapped_column(Float)
    geo_source: Mapped[str | None] = mapped_column(String(16))  # exif | site | entity | manual
    captured_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    era_year: Mapped[int | None] = mapped_column(Integer, index=True)
    site_id: Mapped[int | None] = mapped_column(ForeignKey("sites.id", ondelete="SET NULL"), index=True)
    journey_id: Mapped[int | None] = mapped_column(ForeignKey("journeys.id", ondelete="SET NULL"), index=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("assets.id", ondelete="SET NULL"), index=True)
    language: Mapped[str | None] = mapped_column(String(8), index=True)
    contributor: Mapped[str | None] = mapped_column(String(120))
    license: Mapped[str | None] = mapped_column(String(80))
    attribution: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(Text)
    caption: Mapped[str | None] = mapped_column(Text)
    caption_source: Mapped[str | None] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(16), default=AssetStatus.queued, index=True)
    error: Mapped[str | None] = mapped_column(Text)
    meta: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    image_embedding: Mapped[np.ndarray | None] = mapped_column(Vector(IMAGE_DIM))

    site: Mapped[Site | None] = relationship(back_populates="assets", foreign_keys=[site_id])
    journey: Mapped[Journey | None] = relationship()
    pages: Mapped[list[Page]] = relationship(
        back_populates="asset", cascade="all, delete-orphan", order_by="Page.page_no"
    )

    __table_args__ = (hnsw_cosine_index("ix_assets_image_embedding_hnsw", "image_embedding"),)


class Page(Base):
    __tablename__ = "pages"

    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), index=True)
    page_no: Mapped[int] = mapped_column(Integer)
    image_key: Mapped[str | None] = mapped_column(String(200))
    text: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(16), default="native")  # native | ocr | seed
    needs_ocr: Mapped[bool] = mapped_column(Boolean, default=False)
    ocr_engine: Mapped[str | None] = mapped_column(String(60))
    ocr_confidence: Mapped[float | None] = mapped_column(Float)
    language: Mapped[str | None] = mapped_column(String(8))

    asset: Mapped[Asset] = relationship(back_populates="pages")

    __table_args__ = (UniqueConstraint("asset_id", "page_no", name="uq_pages_asset_page"),)


class Chunk(Base):
    """A retrievable passage. Indexed lexically (text + translation + phonetic key) and semantically."""

    __tablename__ = "chunks"

    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), index=True)
    page_no: Mapped[int] = mapped_column(Integer, default=1)
    seq: Mapped[int] = mapped_column(Integer, default=0)
    char_start: Mapped[int] = mapped_column(Integer, default=0)
    text: Mapped[str] = mapped_column(Text)
    language: Mapped[str | None] = mapped_column(String(8), index=True)
    script: Mapped[str | None] = mapped_column(String(8))
    translation: Mapped[str | None] = mapped_column(Text)
    translation_engine: Mapped[str | None] = mapped_column(String(80))
    phonetic: Mapped[str] = mapped_column(Text, default="")
    embedding: Mapped[np.ndarray | None] = mapped_column(Vector(TEXT_DIM))
    embed_model: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)

    asset: Mapped[Asset] = relationship()

    __table_args__ = (
        Index("ix_chunks_fts", sql_text(chunk_fts_sql()), postgresql_using="gin").ddl_if(dialect="postgresql"),
        hnsw_cosine_index("ix_chunks_embedding_hnsw", "embedding"),
    )


class Entity(Base):
    __tablename__ = "entities"

    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), index=True)
    chunk_id: Mapped[int] = mapped_column(ForeignKey("chunks.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16), index=True)  # site | place | date
    surface: Mapped[str] = mapped_column(String(200))
    normalized: Mapped[str] = mapped_column(String(200))
    site_id: Mapped[int | None] = mapped_column(ForeignKey("sites.id", ondelete="SET NULL"), index=True)
    lat: Mapped[float | None] = mapped_column(Float)
    lon: Mapped[float | None] = mapped_column(Float)
    year: Mapped[int | None] = mapped_column(Integer)
    start: Mapped[int] = mapped_column(Integer, default=0)
    end: Mapped[int] = mapped_column(Integer, default=0)


class Twin(TimestampMixin, Base):
    """A 3D digital twin of a site (point cloud, gaussian splat or mesh)."""

    __tablename__ = "twins"

    id: Mapped[int] = mapped_column(primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    method: Mapped[str] = mapped_column(String(32))  # procedural | depth-relief | gaussian-splat | photogrammetry
    format: Mapped[str] = mapped_column(String(8))  # ply | splat | glb
    storage_key: Mapped[str] = mapped_column(String(200))
    point_count: Mapped[int | None] = mapped_column(Integer)
    source_asset_ids: Mapped[list[int]] = mapped_column(JSONType, default=list)
    meta: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)

    site: Mapped[Site] = relationship(back_populates="twins")


class Job(TimestampMixin, Base):
    """Durable, lease-based work queue living in the primary database (no broker needed).

    Workers - local CPU processes or remote Colab GPUs behind NAT - *pull* jobs via an atomic
    compare-and-set lease. Expired leases are re-queued, failures retried with backoff, and
    exhausted jobs moved to a dead-letter state.
    """

    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str] = mapped_column(String(32), index=True)
    queue: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), default=JobStatus.queued)
    priority: Mapped[int] = mapped_column(Integer, default=100)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    dedupe_key: Mapped[str | None] = mapped_column(String(120), index=True)
    asset_id: Mapped[int | None] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), index=True)
    site_id: Mapped[int | None] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    run_after: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    lease_owner: Mapped[str | None] = mapped_column(String(64))
    lease_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime())

    __table_args__ = (Index("ix_jobs_dispatch", "queue", "status", "priority", "id"),)


class Worker(Base):
    __tablename__ = "workers"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    queue: Mapped[str] = mapped_column(String(16))
    device: Mapped[str | None] = mapped_column(String(120))
    capabilities: Mapped[list[str]] = mapped_column(JSONType, default=list)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, index=True)
    jobs_done: Mapped[int] = mapped_column(Integer, default=0)
    jobs_failed: Mapped[int] = mapped_column(Integer, default=0)
