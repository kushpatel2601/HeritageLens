"""Deterministic, model-free engines.

They speak the full protocol (fetch inputs, upload artifacts, return schema-valid results) so the
end-to-end pipeline can be demonstrated and contract-tested on any laptop or CI runner without a GPU
or model downloads. Outputs are clearly labelled as synthetic.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from PIL import ImageFilter

from heritage_gpu.engines.base import Engine, JobIO, decode_image
from heritage_gpu.geometry import relief_from_disparity, write_ply
from heritage_gpu.langs import NAMES
from heritage_gpu.textproc import normalize


class FakeOCR(Engine):
    job_type = "ocr"

    @property
    def name(self) -> str:
        return "fake-ocr"

    def run(self, payload: dict[str, Any], io: JobIO) -> dict[str, Any]:
        pages = []
        for page in payload["pages"]:
            io.check_cancelled()
            img = decode_image(io.fetch(page["image_key"]), max_side=256)
            ink = 1.0 - float(np.asarray(img.convert("L"), dtype=np.float32).mean()) / 255.0
            text = f"Synthetic transcription of page {page['page_no']} (ink coverage {ink:.0%})."
            pages.append({"page_no": int(page["page_no"]), "text": text, "confidence": 0.5})
        return {"engine": self.name, "pages": pages}


class FakeTranslator(Engine):
    job_type = "translate"

    @property
    def name(self) -> str:
        return "fake-translate"

    def run(self, payload: dict[str, Any], io: JobIO) -> dict[str, Any]:
        items = []
        for item in payload["items"]:
            lang = item.get("lang") or payload.get("src_lang") or "?"
            text = normalize(item.get("text") or "")
            if text:
                label = NAMES.get(lang, lang)
                items.append({"chunk_id": int(item["chunk_id"]), "translation": f"[synthetic {label} gloss] {text}"})
        return {"engine": self.name, "items": items}


class FakeCaptioner(Engine):
    job_type = "caption"

    @property
    def name(self) -> str:
        return "fake-caption"

    def run(self, payload: dict[str, Any], io: JobIO) -> dict[str, Any]:
        img = decode_image(io.fetch(payload["image_key"]), max_side=256)
        r, g, b = np.asarray(img, dtype=np.float32).reshape(-1, 3).mean(axis=0)
        tone = "warm" if r > b else "cool"
        light = "bright" if (r + g + b) / 3 > 128 else "dim"
        shape = "landscape" if img.width >= img.height else "portrait"
        return {"engine": self.name, "caption": f"A {light}, {tone}-toned {shape} photograph (synthetic caption)"}


def luminance_disparity(rgb: np.ndarray) -> np.ndarray:
    """A cheap stand-in for monocular depth: brighter = nearer, plus a ground-plane gradient."""
    from PIL import Image

    img = Image.fromarray(rgb).convert("L")
    blurred = img.filter(ImageFilter.GaussianBlur(radius=max(2, img.width // 100)))
    lum = np.asarray(blurred, dtype=np.float32) / 255.0
    ground = np.linspace(0.0, 1.0, lum.shape[0], dtype=np.float32)[:, None]
    return 0.55 * lum + 0.45 * ground


class FakeReconstructor(Engine):
    job_type = "reconstruct3d"

    @property
    def name(self) -> str:
        return "fake-relief"

    def run(self, payload: dict[str, Any], io: JobIO) -> dict[str, Any]:
        first = payload["images"][0]
        img = decode_image(io.fetch(first["image_key"]), max_side=640)
        rgb = np.asarray(img)
        cloud = relief_from_disparity(rgb, luminance_disparity(rgb), max_points=60_000)
        artifact = io.upload_artifact(
            f"relief-{first['asset_id']}.ply", write_ply(cloud, "HeritageLens luminance relief")
        )
        return {
            "artifact_key": artifact["key"],
            "format": "ply",
            "method": "luminance-relief",
            "point_count": len(cloud),
            "title": payload.get("title"),
            "source_asset_ids": [int(first["asset_id"])],
        }


FAKE_ENGINES: tuple[type[Engine], ...] = (FakeOCR, FakeTranslator, FakeCaptioner, FakeReconstructor)
