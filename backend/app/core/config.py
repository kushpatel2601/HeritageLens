from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Twelve-factor configuration. Every value can be overridden with an `HL_` env var."""

    model_config = SettingsConfigDict(env_prefix="HL_", env_file=".env", extra="ignore")

    env: Literal["dev", "test", "prod"] = "dev"
    app_name: str = "HeritageLens"
    log_level: str = "INFO"
    log_json: bool = False

    # Postgres (prod): postgresql+asyncpg://user:pass@host/db  - SQLite (dev/test): sqlite+aiosqlite:///./x.db
    database_url: str = f"sqlite+aiosqlite:///{(BACKEND_DIR / 'var' / 'heritagelens.db').as_posix()}"
    db_echo: bool = False
    auto_create_schema: bool = True  # SQLite quick-start only; PostgreSQL is managed by Alembic

    # Object storage
    storage_backend: Literal["local", "s3"] = "local"
    storage_dir: Path = BACKEND_DIR / "var" / "storage"
    s3_bucket: str = "heritagelens"
    s3_endpoint_url: str | None = None
    s3_region: str = "us-east-1"
    s3_access_key: str | None = None
    s3_secret_key: str | None = None

    # Security
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])
    worker_token: str = "dev-worker-token"
    ingest_token: str | None = None  # when set, uploads require `Authorization: Bearer <token>`
    max_upload_mb: int = 200
    max_pdf_pages: int = 400

    # ML / search
    # auto = the lean export when present, else fastembed when installed, else the hashing fallback.
    embedder: Literal["auto", "lean", "fastembed", "hashing"] = "auto"
    text_embed_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    # Output of `app.cli export-lean-model`: the same text model in ~170 MB of RAM instead of ~500 MB.
    lean_model_dir: Path = BACKEND_DIR / "var" / "models" / "lean-minilm"
    embed_threads: int = 0  # ONNX Runtime intra-op threads for text embeddings; 0 = one per core
    # Load the text model in the background at start-up so the first search after a (cold) boot is fast.
    warm_embedder: bool = False
    image_embed_model: str = "Qdrant/clip-ViT-B-32-vision"
    image_text_embed_model: str = "Qdrant/clip-ViT-B-32-text"
    enable_image_search: bool = True
    embed_dim: int = 384
    image_embed_dim: int = 512
    rrf_k: int = 60
    semantic_min_score: float = 0.3  # cosine floor for a vector-only hit to count as relevant
    clip_min_score: float = 0.24  # CLIP text->image cosine floor
    # MiniLM truncates at 128 word-pieces; ~480 chars of Indic text stays inside that window.
    chunk_chars: int = 480
    chunk_overlap: int = 80

    # Jobs / workers
    embedded_worker: bool = True  # run a CPU worker inside the API process (handy for single-box demos)
    embedded_worker_concurrency: int = 2
    job_lease_seconds: int = 300
    job_max_attempts: int = 3
    worker_poll_seconds: float = 1.0
    gpu_jobs: list[str] = Field(default_factory=lambda: ["ocr", "translate", "caption", "reconstruct3d"])
    # When a GPU job type has a CPU implementation available (e.g. Tesseract OCR) route it to the CPU queue.
    gpu_fallback_to_cpu: bool = True
    enable_captions: bool = True
    worker_offline_after_seconds: int = 60

    # Outbound HTTP (seed photo fallback). Wikimedia requires a contact URL or e-mail in the UA.
    http_user_agent: str = "HeritageLens/0.1 (+https://github.com/vishwapatel2-cmyk; heritage archive demo)"

    @field_validator("cors_origins", "gpu_jobs", mode="before")
    @classmethod
    def _split_csv(cls, v: object) -> object:
        if isinstance(v, str) and not v.strip().startswith("["):
            return [s.strip() for s in v.split(",") if s.strip()]
        return v

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


@lru_cache
def get_settings() -> Settings:
    return Settings()
