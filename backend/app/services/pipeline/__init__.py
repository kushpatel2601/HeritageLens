"""Asset processing DAG.

upload ─► extract ─┬─► ocr (GPU | Tesseract) ─► index ─┬─► translate (GPU) ─► index
                   └────────────────────────────► index ├─► caption (GPU)   ─► index
                                                        └─► image_embed (CLIP, CPU)
site photos ─► reconstruct3d (GPU) ─► Twin
"""

from app.services.pipeline import enrich, extract, index  # noqa: F401  (registers handlers)
from app.services.pipeline.base import (
    HANDLERS,
    Handler,
    InvalidResultError,
    JobContext,
    enqueue_index,
    fail_job,
    get_handler,
    reap,
    settle_job,
)

__all__ = [
    "HANDLERS",
    "Handler",
    "InvalidResultError",
    "JobContext",
    "enqueue_index",
    "fail_job",
    "get_handler",
    "reap",
    "settle_job",
]
