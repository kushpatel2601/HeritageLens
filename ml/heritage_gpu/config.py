"""Worker configuration: environment variables (``HERITAGE_*``) overridden by CLI flags."""

from __future__ import annotations

import os
from dataclasses import dataclass, field, fields, replace
from pathlib import Path
from typing import Any

ALL_JOB_TYPES: tuple[str, ...] = ("ocr", "translate", "caption", "reconstruct3d")


def api_base(url: str) -> str:
    """Accept either the server root (``https://x.trycloudflare.com``) or the versioned API root."""
    url = url.strip().rstrip("/")
    if not url.startswith(("http://", "https://")):
        raise ValueError(f"API URL must start with http:// or https:// (got {url!r})")
    return url if "/api/" in url + "/" else f"{url}/api/v1"


@dataclass(frozen=True, slots=True)
class WorkerConfig:
    api_url: str = "http://localhost:8000"
    token: str = "dev-worker-token"
    name: str = "colab-gpu"
    job_types: tuple[str, ...] = ALL_JOB_TYPES

    # Protocol timing. The server marks a worker offline after 60 s without contact and extends a
    # lease by 300 s per heartbeat, so idle polling must stay well under the former.
    lease_seconds: int = 300
    heartbeat_seconds: float = 60.0
    poll_min_seconds: float = 1.0
    poll_max_seconds: float = 10.0
    http_timeout_seconds: float = 120.0
    http_retries: int = 4

    # Lifecycle
    max_jobs: int | None = None
    idle_exit_seconds: float | None = None
    fake: bool = False
    device: str = "auto"  # auto | cuda | cpu
    work_dir: Path = field(default_factory=lambda: Path("outputs"))

    # Engines
    ocr_engine: str = "tesseract"  # tesseract | vlm
    ocr_model: str = "Qwen/Qwen2.5-VL-3B-Instruct"
    ocr_default_langs: str = "guj+hin+eng"
    translator: str = "auto"  # auto (IndicTrans2 -> NLLB) | indictrans2 | nllb
    indictrans_model: str = "ai4bharat/indictrans2-indic-en-dist-200M"
    nllb_model: str = "facebook/nllb-200-distilled-600M"
    translate_batch_size: int = 16
    caption_model: str = "Salesforce/blip-image-captioning-large"
    depth_model: str = "depth-anything/Depth-Anything-V2-Base-hf"
    relief_max_points: int = 600_000
    splat_steps: int = 7000

    def __post_init__(self) -> None:
        unknown = set(self.job_types) - set(ALL_JOB_TYPES)
        if unknown:
            raise ValueError(f"unknown job types: {sorted(unknown)} (choose from {', '.join(ALL_JOB_TYPES)})")
        if not self.job_types:
            raise ValueError("at least one job type is required")
        if self.heartbeat_seconds >= self.lease_seconds:
            raise ValueError("heartbeat interval must be shorter than the lease")
        if not 30 <= self.lease_seconds <= 3600:
            raise ValueError("lease_seconds must be between 30 and 3600")
        api_base(self.api_url)

    @property
    def base_url(self) -> str:
        return api_base(self.api_url)

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None, **overrides: Any) -> WorkerConfig:
        """Build from ``HERITAGE_<FIELD>`` variables; explicit ``overrides`` (e.g. CLI flags) win."""
        env = dict(os.environ if env is None else env)
        values: dict[str, Any] = {}
        for f in fields(cls):
            raw = env.get(f"HERITAGE_{f.name.upper()}")
            if raw is not None and raw != "":
                values[f.name] = _coerce(f.name, raw)
        values.update({k: v for k, v in overrides.items() if v is not None})
        return replace(cls(), **values)


def _coerce(name: str, raw: str) -> Any:
    ints = {"lease_seconds", "http_retries", "max_jobs", "translate_batch_size", "relief_max_points", "splat_steps"}
    floats = {"heartbeat_seconds", "poll_min_seconds", "poll_max_seconds", "http_timeout_seconds", "idle_exit_seconds"}
    if name in ints:
        return int(raw)
    if name in floats:
        return float(raw)
    if name == "fake":
        return raw.strip().lower() in ("1", "true", "yes", "on")
    if name == "job_types":
        return tuple(t.strip() for t in raw.split(",") if t.strip())
    if name == "work_dir":
        return Path(raw)
    return raw
