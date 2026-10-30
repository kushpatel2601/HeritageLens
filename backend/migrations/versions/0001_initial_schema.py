"""initial schema: archive catalogue, durable job queue, pgvector HNSW + full-text GIN indexes

Revision ID: 0001
Revises:
Create Date: 2026-10-29 20:54:36.558323
"""

from collections.abc import Sequence

import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.core.config import get_settings

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Vector widths follow the configured embedding models (HL_EMBED_DIM / HL_IMAGE_EMBED_DIM).
_settings = get_settings()
TEXT_DIM = _settings.embed_dim
IMAGE_DIM = _settings.image_embed_dim


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "journeys",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("slug", sa.String(length=120), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("fellow", sa.String(length=120), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("region", sa.String(length=120), nullable=True),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("color", sa.String(length=16), nullable=False),
        sa.Column("cover_asset_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_journeys")),
    )
    op.create_index(op.f("ix_journeys_slug"), "journeys", ["slug"], unique=True)
    op.create_index(op.f("ix_journeys_updated_at"), "journeys", ["updated_at"], unique=False)
    op.create_index(op.f("ix_journeys_year"), "journeys", ["year"], unique=False)
    op.create_table(
        "sites",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("slug", sa.String(length=120), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("name_native", sa.String(length=200), nullable=True),
        sa.Column("alt_names", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("state", sa.String(length=80), nullable=True),
        sa.Column("district", sa.String(length=80), nullable=True),
        sa.Column("lat", sa.Float(), nullable=False),
        sa.Column("lon", sa.Float(), nullable=False),
        sa.Column("era_start", sa.Integer(), nullable=True),
        sa.Column("era_end", sa.Integer(), nullable=True),
        sa.Column("era_label", sa.String(length=120), nullable=True),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("tags", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("unesco", sa.Boolean(), nullable=False),
        sa.Column("phonetic", sa.Text(), nullable=False),
        sa.Column("cover_asset_id", sa.Integer(), nullable=True),
        sa.Column("embedding", pgvector.sqlalchemy.Vector(TEXT_DIM), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sites")),
    )
    op.create_index(op.f("ix_sites_category"), "sites", ["category"], unique=False)
    op.create_index(
        "ix_sites_embedding_hnsw",
        "sites",
        ["embedding"],
        unique=False,
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.create_index(op.f("ix_sites_era_start"), "sites", ["era_start"], unique=False)
    op.create_index("ix_sites_lat_lon", "sites", ["lat", "lon"], unique=False)
    op.create_index(op.f("ix_sites_slug"), "sites", ["slug"], unique=True)
    op.create_index(op.f("ix_sites_state"), "sites", ["state"], unique=False)
    op.create_index(op.f("ix_sites_updated_at"), "sites", ["updated_at"], unique=False)
    op.create_table(
        "workers",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("queue", sa.String(length=16), nullable=False),
        sa.Column("device", sa.String(length=120), nullable=True),
        sa.Column(
            "capabilities",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("jobs_done", sa.Integer(), nullable=False),
        sa.Column("jobs_failed", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workers")),
    )
    op.create_index(op.f("ix_workers_last_seen_at"), "workers", ["last_seen_at"], unique=False)
    op.create_table(
        "assets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("original_filename", sa.String(length=300), nullable=False),
        sa.Column("mime", sa.String(length=120), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("storage_key", sa.String(length=200), nullable=False),
        sa.Column("thumb_key", sa.String(length=200), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("phash", sa.String(length=16), nullable=True),
        sa.Column("lat", sa.Float(), nullable=True),
        sa.Column("lon", sa.Float(), nullable=True),
        sa.Column("geo_source", sa.String(length=16), nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("era_year", sa.Integer(), nullable=True),
        sa.Column("site_id", sa.Integer(), nullable=True),
        sa.Column("journey_id", sa.Integer(), nullable=True),
        sa.Column("parent_id", sa.Integer(), nullable=True),
        sa.Column("language", sa.String(length=8), nullable=True),
        sa.Column("contributor", sa.String(length=120), nullable=True),
        sa.Column("license", sa.String(length=80), nullable=True),
        sa.Column("attribution", sa.Text(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("caption", sa.Text(), nullable=True),
        sa.Column("caption_source", sa.String(length=40), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("meta", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("image_embedding", pgvector.sqlalchemy.Vector(IMAGE_DIM), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["journey_id"], ["journeys.id"], name=op.f("fk_assets_journey_id_journeys"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"], ["assets.id"], name=op.f("fk_assets_parent_id_assets"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], name=op.f("fk_assets_site_id_sites"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_assets")),
    )
    op.create_index(op.f("ix_assets_era_year"), "assets", ["era_year"], unique=False)
    op.create_index(
        "ix_assets_image_embedding_hnsw",
        "assets",
        ["image_embedding"],
        unique=False,
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"image_embedding": "vector_cosine_ops"},
    )
    op.create_index(op.f("ix_assets_journey_id"), "assets", ["journey_id"], unique=False)
    op.create_index(op.f("ix_assets_kind"), "assets", ["kind"], unique=False)
    op.create_index(op.f("ix_assets_language"), "assets", ["language"], unique=False)
    op.create_index(op.f("ix_assets_parent_id"), "assets", ["parent_id"], unique=False)
    op.create_index(op.f("ix_assets_phash"), "assets", ["phash"], unique=False)
    op.create_index(op.f("ix_assets_sha256"), "assets", ["sha256"], unique=True)
    op.create_index(op.f("ix_assets_site_id"), "assets", ["site_id"], unique=False)
    op.create_index(op.f("ix_assets_status"), "assets", ["status"], unique=False)
    op.create_index(op.f("ix_assets_updated_at"), "assets", ["updated_at"], unique=False)
    op.create_table(
        "journey_stops",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("journey_id", sa.Integer(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("site_id", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("lat", sa.Float(), nullable=False),
        sa.Column("lon", sa.Float(), nullable=False),
        sa.Column("visited_on", sa.Date(), nullable=True),
        sa.Column("narrative", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["journey_id"], ["journeys.id"], name=op.f("fk_journey_stops_journey_id_journeys"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["site_id"], ["sites.id"], name=op.f("fk_journey_stops_site_id_sites"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_journey_stops")),
        sa.UniqueConstraint("journey_id", "seq", name="uq_journey_stops_journey_seq"),
    )
    op.create_index(op.f("ix_journey_stops_journey_id"), "journey_stops", ["journey_id"], unique=False)
    op.create_index(op.f("ix_journey_stops_site_id"), "journey_stops", ["site_id"], unique=False)
    op.create_table(
        "twins",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("site_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("method", sa.String(length=32), nullable=False),
        sa.Column("format", sa.String(length=8), nullable=False),
        sa.Column("storage_key", sa.String(length=200), nullable=False),
        sa.Column("point_count", sa.Integer(), nullable=True),
        sa.Column(
            "source_asset_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("meta", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], name=op.f("fk_twins_site_id_sites"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_twins")),
    )
    op.create_index(op.f("ix_twins_site_id"), "twins", ["site_id"], unique=False)
    op.create_index(op.f("ix_twins_updated_at"), "twins", ["updated_at"], unique=False)
    op.create_table(
        "chunks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=False),
        sa.Column("page_no", sa.Integer(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("char_start", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("language", sa.String(length=8), nullable=True),
        sa.Column("script", sa.String(length=8), nullable=True),
        sa.Column("translation", sa.Text(), nullable=True),
        sa.Column("translation_engine", sa.String(length=80), nullable=True),
        sa.Column("phonetic", sa.Text(), nullable=False),
        sa.Column("embedding", pgvector.sqlalchemy.Vector(TEXT_DIM), nullable=True),
        sa.Column("embed_model", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["asset_id"], ["assets.id"], name=op.f("fk_chunks_asset_id_assets"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chunks")),
    )
    op.create_index(op.f("ix_chunks_asset_id"), "chunks", ["asset_id"], unique=False)
    op.create_index(
        "ix_chunks_embedding_hnsw",
        "chunks",
        ["embedding"],
        unique=False,
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.create_index(
        "ix_chunks_fts",
        "chunks",
        [
            sa.literal_column(
                "to_tsvector('simple'::regconfig, coalesce(text, '') || ' ' || coalesce(translation, '') "
                "|| ' ' || coalesce(phonetic, ''))"
            )
        ],
        unique=False,
        postgresql_using="gin",
    )
    op.create_index(op.f("ix_chunks_language"), "chunks", ["language"], unique=False)
    op.create_table(
        "jobs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("queue", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("dedupe_key", sa.String(length=120), nullable=True),
        sa.Column("asset_id", sa.Integer(), nullable=True),
        sa.Column("site_id", sa.Integer(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("run_after", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_owner", sa.String(length=64), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], name=op.f("fk_jobs_asset_id_assets"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], name=op.f("fk_jobs_site_id_sites"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_jobs")),
    )
    op.create_index(op.f("ix_jobs_asset_id"), "jobs", ["asset_id"], unique=False)
    op.create_index(op.f("ix_jobs_dedupe_key"), "jobs", ["dedupe_key"], unique=False)
    op.create_index("ix_jobs_dispatch", "jobs", ["queue", "status", "priority", "id"], unique=False)
    op.create_index(op.f("ix_jobs_site_id"), "jobs", ["site_id"], unique=False)
    op.create_index(op.f("ix_jobs_type"), "jobs", ["type"], unique=False)
    op.create_index(op.f("ix_jobs_updated_at"), "jobs", ["updated_at"], unique=False)
    op.create_table(
        "pages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=False),
        sa.Column("page_no", sa.Integer(), nullable=False),
        sa.Column("image_key", sa.String(length=200), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("needs_ocr", sa.Boolean(), nullable=False),
        sa.Column("ocr_engine", sa.String(length=60), nullable=True),
        sa.Column("ocr_confidence", sa.Float(), nullable=True),
        sa.Column("language", sa.String(length=8), nullable=True),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], name=op.f("fk_pages_asset_id_assets"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pages")),
        sa.UniqueConstraint("asset_id", "page_no", name="uq_pages_asset_page"),
    )
    op.create_index(op.f("ix_pages_asset_id"), "pages", ["asset_id"], unique=False)
    op.create_table(
        "entities",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=False),
        sa.Column("chunk_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("surface", sa.String(length=200), nullable=False),
        sa.Column("normalized", sa.String(length=200), nullable=False),
        sa.Column("site_id", sa.Integer(), nullable=True),
        sa.Column("lat", sa.Float(), nullable=True),
        sa.Column("lon", sa.Float(), nullable=True),
        sa.Column("year", sa.Integer(), nullable=True),
        sa.Column("start", sa.Integer(), nullable=False),
        sa.Column("end", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["asset_id"], ["assets.id"], name=op.f("fk_entities_asset_id_assets"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["chunk_id"], ["chunks.id"], name=op.f("fk_entities_chunk_id_chunks"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], name=op.f("fk_entities_site_id_sites"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_entities")),
    )
    op.create_index(op.f("ix_entities_asset_id"), "entities", ["asset_id"], unique=False)
    op.create_index(op.f("ix_entities_chunk_id"), "entities", ["chunk_id"], unique=False)
    op.create_index(op.f("ix_entities_kind"), "entities", ["kind"], unique=False)
    op.create_index(op.f("ix_entities_site_id"), "entities", ["site_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_entities_site_id"), table_name="entities")
    op.drop_index(op.f("ix_entities_kind"), table_name="entities")
    op.drop_index(op.f("ix_entities_chunk_id"), table_name="entities")
    op.drop_index(op.f("ix_entities_asset_id"), table_name="entities")
    op.drop_table("entities")
    op.drop_index(op.f("ix_pages_asset_id"), table_name="pages")
    op.drop_table("pages")
    op.drop_index(op.f("ix_jobs_updated_at"), table_name="jobs")
    op.drop_index(op.f("ix_jobs_type"), table_name="jobs")
    op.drop_index(op.f("ix_jobs_site_id"), table_name="jobs")
    op.drop_index("ix_jobs_dispatch", table_name="jobs")
    op.drop_index(op.f("ix_jobs_dedupe_key"), table_name="jobs")
    op.drop_index(op.f("ix_jobs_asset_id"), table_name="jobs")
    op.drop_table("jobs")
    op.drop_index(op.f("ix_chunks_language"), table_name="chunks")
    op.drop_index("ix_chunks_fts", table_name="chunks", postgresql_using="gin")
    op.drop_index(
        "ix_chunks_embedding_hnsw",
        table_name="chunks",
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.drop_index(op.f("ix_chunks_asset_id"), table_name="chunks")
    op.drop_table("chunks")
    op.drop_index(op.f("ix_twins_updated_at"), table_name="twins")
    op.drop_index(op.f("ix_twins_site_id"), table_name="twins")
    op.drop_table("twins")
    op.drop_index(op.f("ix_journey_stops_site_id"), table_name="journey_stops")
    op.drop_index(op.f("ix_journey_stops_journey_id"), table_name="journey_stops")
    op.drop_table("journey_stops")
    op.drop_index(op.f("ix_assets_updated_at"), table_name="assets")
    op.drop_index(op.f("ix_assets_status"), table_name="assets")
    op.drop_index(op.f("ix_assets_site_id"), table_name="assets")
    op.drop_index(op.f("ix_assets_sha256"), table_name="assets")
    op.drop_index(op.f("ix_assets_phash"), table_name="assets")
    op.drop_index(op.f("ix_assets_parent_id"), table_name="assets")
    op.drop_index(op.f("ix_assets_language"), table_name="assets")
    op.drop_index(op.f("ix_assets_kind"), table_name="assets")
    op.drop_index(op.f("ix_assets_journey_id"), table_name="assets")
    op.drop_index(
        "ix_assets_image_embedding_hnsw",
        table_name="assets",
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"image_embedding": "vector_cosine_ops"},
    )
    op.drop_index(op.f("ix_assets_era_year"), table_name="assets")
    op.drop_table("assets")
    op.drop_index(op.f("ix_workers_last_seen_at"), table_name="workers")
    op.drop_table("workers")
    op.drop_index(op.f("ix_sites_updated_at"), table_name="sites")
    op.drop_index(op.f("ix_sites_state"), table_name="sites")
    op.drop_index(op.f("ix_sites_slug"), table_name="sites")
    op.drop_index("ix_sites_lat_lon", table_name="sites")
    op.drop_index(op.f("ix_sites_era_start"), table_name="sites")
    op.drop_index(
        "ix_sites_embedding_hnsw",
        table_name="sites",
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.drop_index(op.f("ix_sites_category"), table_name="sites")
    op.drop_table("sites")
    op.drop_index(op.f("ix_journeys_year"), table_name="journeys")
    op.drop_index(op.f("ix_journeys_updated_at"), table_name="journeys")
    op.drop_index(op.f("ix_journeys_slug"), table_name="journeys")
    op.drop_table("journeys")
