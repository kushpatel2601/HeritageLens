"""Wire contracts for the pull-based worker protocol (local CPU workers and remote Colab GPUs)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class WorkerRegister(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    queue: Literal["cpu", "gpu"] = "gpu"
    device: str | None = Field(default=None, max_length=120)
    capabilities: list[str] = Field(default_factory=list, max_length=16)


class WorkerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    queue: str
    device: str | None
    capabilities: list[str]
    started_at: datetime
    last_seen_at: datetime
    jobs_done: int
    jobs_failed: int
    online: bool = False


class LeaseRequest(BaseModel):
    types: list[str] | None = None
    limit: int = Field(default=1, ge=1, le=8)
    lease_seconds: int | None = Field(default=None, ge=30, le=3600)


class LeasedJob(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    type: str
    payload: dict[str, Any]
    attempts: int
    lease_expires_at: datetime | None


class LeaseResponse(BaseModel):
    jobs: list[LeasedJob]


class CompleteRequest(BaseModel):
    result: dict[str, Any] = Field(default_factory=dict)


class FailRequest(BaseModel):
    error: str = Field(max_length=4000)
    retryable: bool = True


class ArtifactOut(BaseModel):
    key: str
    size_bytes: int
    format: str
    point_count: int | None = None


# ---------------------------------------------------------------- typed GPU job results
class OcrPageResult(BaseModel):
    page_no: int = Field(ge=1)
    text: str = Field(max_length=200_000)
    confidence: float | None = Field(default=None, ge=0, le=1)


class OcrResult(BaseModel):
    engine: str = Field(max_length=60)
    pages: list[OcrPageResult] = Field(max_length=1000)


class TranslationItem(BaseModel):
    chunk_id: int
    translation: str = Field(max_length=20_000)


class TranslateResult(BaseModel):
    engine: str = Field(max_length=80)
    items: list[TranslationItem] = Field(max_length=5000)


class CaptionResult(BaseModel):
    engine: str = Field(max_length=40)
    caption: str = Field(min_length=1, max_length=1000)


class ReconstructResult(BaseModel):
    artifact_key: str = Field(max_length=200)
    format: Literal["ply", "splat", "glb"]
    method: str = Field(max_length=32)
    point_count: int | None = Field(default=None, ge=0)
    title: str | None = Field(default=None, max_length=200)
    source_asset_ids: list[int] = Field(default_factory=list)
