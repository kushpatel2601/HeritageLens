"""``heritage-gpu selftest``: run every configured engine once on synthetic inputs, offline.

Used by the Colab notebook to prove the GPU stack (CUDA, Tesseract language packs, model downloads)
works *before* the worker goes live, and by CI with ``--fake``.
"""

from __future__ import annotations

import io
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from heritage_gpu.engines import Engine

log = logging.getLogger(__name__)

GUJARATI = "રાણીની વાવ પાટણમાં આવેલી અગિયારમી સદીની એક સુંદર વાવ છે. તેની દીવાલો પર સેંકડો શિલ્પો કોતરેલાં છે."
HINDI = "चाँद बावड़ी राजस्थान के आभानेरी गाँव में स्थित है। इसमें साढ़े तीन हज़ार सीढ़ियाँ हैं।"


@dataclass
class MemoryIO:
    """In-memory :class:`heritage_gpu.engines.JobIO` - also handy in tests."""

    blobs: dict[str, bytes]
    job_id: int = 0
    artifacts: dict[str, bytes] = field(default_factory=dict)
    messages: list[str] = field(default_factory=list)

    def fetch(self, key: str) -> bytes:
        return self.blobs[key]

    def upload_artifact(self, filename: str, data: bytes) -> dict[str, Any]:
        key = f"twins/site-0/job-{self.job_id}/{filename}"
        self.artifacts[key] = data
        return {"key": key, "size_bytes": len(data), "format": filename.rsplit(".", 1)[-1], "point_count": None}

    def check_cancelled(self) -> None:
        return None

    def progress(self, message: str) -> None:
        self.messages.append(message)
        log.info("selftest: %s", message)


def _font(size: int) -> Any:
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow < 10.1
        return ImageFont.load_default()


def _png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def synthetic_page() -> bytes:
    img = Image.new("RGB", (1400, 600), (246, 240, 226))
    draw = ImageDraw.Draw(img)
    for i, line in enumerate(("Survey of Patan, 1885", "Rani ki Vav stepwell", "Seven storeys, silted")):
        draw.text((80, 90 + i * 150), line, fill=(40, 30, 20), font=_font(72))
    return _png(img)


def synthetic_photo() -> bytes:
    """Sky, ground and a stepped stone structure - enough for depth and captioning to engage."""
    w, h = 960, 640
    img = Image.new("RGB", (w, h))
    draw = ImageDraw.Draw(img)
    for y in range(h):
        t = y / h
        colour = (int(120 + 100 * t), int(170 + 50 * t), 235) if y < h * 0.45 else (150, 120, 80)
        draw.line([(0, y), (w, y)], fill=colour)
    for step in range(7):
        inset, top = 60 + step * 45, int(h * 0.75) - step * 40
        draw.rectangle(
            [inset, top, w - inset, top + 40], fill=(178 - step * 6, 128 - step * 4, 82), outline=(90, 60, 40)
        )
    return _png(img)


def payloads() -> tuple[dict[str, bytes], dict[str, dict[str, Any]]]:
    blobs = {"pages/0/1.png": synthetic_page(), "originals/0/photo.png": synthetic_photo()}
    jobs: dict[str, dict[str, Any]] = {
        "ocr": {"asset_id": 0, "lang_hint": "en", "pages": [{"page_no": 1, "image_key": "pages/0/1.png"}]},
        "translate": {
            "asset_id": 0,
            "src_lang": "gu",
            "items": [{"chunk_id": 1, "text": GUJARATI, "lang": "gu"}, {"chunk_id": 2, "text": HINDI, "lang": "hi"}],
        },
        "caption": {"asset_id": 0, "image_key": "originals/0/photo.png"},
        "reconstruct3d": {
            "site_id": 0,
            "method": "depth-relief",
            "title": "Self-test relief",
            "images": [{"asset_id": 0, "image_key": "originals/0/photo.png"}],
        },
    }
    return blobs, jobs


def _preview(job_type: str, result: dict[str, Any]) -> str:
    if job_type == "ocr":
        return " | ".join(p["text"].replace("\n", " / ")[:120] for p in result["pages"])
    if job_type == "translate":
        return " | ".join(i["translation"][:120] for i in result["items"])
    if job_type == "caption":
        return str(result["caption"])
    return f"{result['method']} {result['format']} with {result['point_count']:,} points"


def run_selftest(engines: dict[str, Engine]) -> bool:
    blobs, jobs = payloads()
    ok = True
    for job_type, engine in engines.items():
        memio = MemoryIO(blobs)
        started = time.monotonic()
        try:
            engine.ensure_loaded()
            loaded = time.monotonic()
            result = engine.run(jobs[job_type], memio)
        except Exception as exc:
            ok = False
            print(f"FAIL {job_type:<13} {engine.name}: {type(exc).__name__}: {exc}")
            continue
        done = time.monotonic()
        print(
            f"ok   {job_type:<13} {engine.name:<38} load {loaded - started:5.1f}s  run {done - loaded:5.1f}s  "
            f"-> {_preview(job_type, result)}"
        )
    return ok
