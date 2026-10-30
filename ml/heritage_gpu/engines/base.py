"""Engine contract.

An engine owns one job type, loads its model lazily (first job, not at import) and turns a job
payload into the result dict the server validates (``app/schemas/worker.py``). Engines never talk
HTTP directly: inputs, artifact uploads and cancellation go through :class:`JobIO`, which keeps them
unit-testable and lets the runner enforce lease ownership.
"""

from __future__ import annotations

import io
from abc import ABC, abstractmethod
from typing import Any, ClassVar, Protocol

from PIL import Image, ImageOps

from heritage_gpu.errors import JobError

MAX_IMAGE_PIXELS = 80_000_000  # refuse decompression bombs before they reach a model


class JobIO(Protocol):
    job_id: int

    def fetch(self, key: str) -> bytes: ...

    def upload_artifact(self, filename: str, data: bytes) -> dict[str, Any]: ...

    def check_cancelled(self) -> None: ...

    def progress(self, message: str) -> None: ...


def decode_image(data: bytes, *, max_side: int | None = None) -> Image.Image:
    """Decode to an upright RGB image (EXIF orientation applied), optionally bounded in size."""
    try:
        with Image.open(io.BytesIO(data)) as src:
            if src.width * src.height > MAX_IMAGE_PIXELS:
                raise JobError(f"image too large ({src.width}x{src.height})", retryable=False)
            img = ImageOps.exif_transpose(src).convert("RGB")
    except (OSError, SyntaxError, ValueError, Image.DecompressionBombError) as exc:
        raise JobError(f"cannot decode image: {exc}", retryable=False) from exc
    if max_side and max(img.size) > max_side:
        img.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    return img


class Engine(ABC):
    job_type: ClassVar[str]

    def __init__(self) -> None:
        self._loaded = False

    @property
    @abstractmethod
    def name(self) -> str:
        """Engine / model identifier stored with the result for provenance."""

    def ensure_loaded(self) -> None:
        if not self._loaded:
            self.load()
            self._loaded = True

    def load(self) -> None:  # noqa: B027 - optional hook
        """Load weights. Called once, on the first job of this type."""

    @abstractmethod
    def run(self, payload: dict[str, Any], io: JobIO) -> dict[str, Any]:
        """Execute one job and return its result (must match the server's result schema)."""
