"""Stage 3 - enrichment. GPU-class jobs (OCR, translation, captioning, 3D) are normally executed by
remote workers (see ``ml/heritage_gpu``); here we validate and persist their results. OCR has a CPU
fallback through Tesseract when it is installed, and CLIP image embeddings run locally via ONNX.
"""

from __future__ import annotations

import asyncio
import io
import logging
from typing import Any

from sqlalchemy import select

from app.db.models import Asset, Job, Page, Site, Twin
from app.schemas.worker import CaptionResult, OcrResult, ReconstructResult, TranslateResult
from app.services.embeddings import get_image_embedder
from app.services.pipeline.base import Handler, InvalidResultError, JobContext, enqueue_index, register
from app.services.pipeline.index import TM_KEY, norm
from app.services.text.scripts import detect_language

log = logging.getLogger(__name__)

TESSERACT_LANGS = ("hin", "guj", "mar", "san", "eng")


@register
class OcrHandler(Handler):
    type = "ocr"
    result_model = OcrResult

    def runs_locally(self, ctx: JobContext) -> bool:
        return ctx.queue.has_cpu_impl("ocr")

    async def run(self, ctx: JobContext, job: Job) -> dict[str, Any]:
        pages = []
        for p in job.payload["pages"]:
            data = await ctx.storage.get(p["image_key"])
            text, conf = await asyncio.to_thread(_tesseract, data)
            pages.append({"page_no": p["page_no"], "text": text, "confidence": conf})
        return {"engine": "tesseract", "pages": pages}

    async def apply(self, ctx: JobContext, session: Any, job: Job, result: dict[str, Any]) -> None:
        asset_id = int(job.payload["asset_id"])
        by_no = {p["page_no"]: p for p in result["pages"]}
        rows = (await session.scalars(select(Page).where(Page.asset_id == asset_id))).all()
        for page in rows:
            hit = by_no.get(page.page_no)
            if hit is None:
                continue
            page.text = hit["text"].strip()
            page.source = "ocr"
            page.ocr_engine = result["engine"]
            page.ocr_confidence = hit["confidence"]
            page.needs_ocr = False
            page.language = detect_language(page.text)[0]
        await session.flush()
        await enqueue_index(ctx, session, asset_id, priority=65)

    def summarize(self, result: dict[str, Any]) -> dict[str, Any]:
        confs = [p["confidence"] for p in result["pages"] if p.get("confidence") is not None]
        return {
            "engine": result["engine"],
            "pages": len(result["pages"]),
            "chars": sum(len(p["text"]) for p in result["pages"]),
            "mean_confidence": round(sum(confs) / len(confs), 3) if confs else None,
        }


def _tesseract(data: bytes) -> tuple[str, float | None]:
    import pytesseract
    from PIL import Image

    available = set(pytesseract.get_languages(config=""))
    langs = "+".join(lang for lang in TESSERACT_LANGS if lang in available) or "eng"
    img = Image.open(io.BytesIO(data)).convert("RGB")
    text = pytesseract.image_to_string(img, lang=langs)
    data_out = pytesseract.image_to_data(img, lang=langs, output_type=pytesseract.Output.DICT)
    confs = [float(c) for c in data_out.get("conf", []) if str(c).strip() not in ("", "-1")]
    return text, (sum(confs) / len(confs) / 100.0 if confs else None)


@register
class TranslateHandler(Handler):
    type = "translate"
    blocking = False
    result_model = TranslateResult

    def runs_locally(self, ctx: JobContext) -> bool:
        return False

    async def apply(self, ctx: JobContext, session: Any, job: Job, result: dict[str, Any]) -> None:
        asset = await session.get(Asset, int(job.payload["asset_id"]))
        if asset is None:
            return
        source_by_id = {int(i["chunk_id"]): i["text"] for i in job.payload.get("items", [])}
        unknown = [i["chunk_id"] for i in result["items"] if i["chunk_id"] not in source_by_id]
        if unknown:
            raise InvalidResultError(f"translations for chunks that were not requested: {unknown[:10]}")
        memory: dict[str, list[str]] = dict((asset.meta or {}).get(TM_KEY, {}))
        returned = {i["chunk_id"]: i["translation"].strip() for i in result["items"]}
        for chunk_id, text in source_by_id.items():
            # Missing / empty answers are remembered as attempted so they are not re-requested forever.
            memory[norm(text)] = [returned.get(chunk_id, ""), result["engine"]]
        asset.meta = {**(asset.meta or {}), TM_KEY: memory}
        await session.flush()
        await enqueue_index(ctx, session, asset.id, priority=110)  # re-embed with the translation

    def summarize(self, result: dict[str, Any]) -> dict[str, Any]:
        return {"engine": result["engine"], "items": len(result["items"])}


@register
class CaptionHandler(Handler):
    type = "caption"
    blocking = False
    result_model = CaptionResult

    def runs_locally(self, ctx: JobContext) -> bool:
        return False

    async def apply(self, ctx: JobContext, session: Any, job: Job, result: dict[str, Any]) -> None:
        asset = await session.get(Asset, int(job.payload["asset_id"]))
        if asset is None or asset.caption_source in ("contributor", "seed"):
            return  # never overwrite human-written captions
        asset.caption = result["caption"].strip()
        asset.caption_source = result["engine"]
        await session.flush()
        await enqueue_index(ctx, session, asset.id, priority=120)


@register
class ImageEmbedHandler(Handler):
    type = "image_embed"
    blocking = False

    async def run(self, ctx: JobContext, job: Job) -> dict[str, Any]:
        embedder = await asyncio.to_thread(get_image_embedder, ctx.settings)
        if embedder is None:
            return {"skipped": "image search disabled"}
        asset_id = int(job.payload["asset_id"])
        async with ctx.db.sessionmaker() as s:
            asset = await s.get(Asset, asset_id)
            if asset is None:
                return {"skipped": "asset deleted"}
            key = asset.thumb_key or asset.storage_key
        data = await ctx.storage.get(key)

        def _embed() -> Any:
            from PIL import Image

            img = Image.open(io.BytesIO(data)).convert("RGB")
            return embedder.embed_images([img])[0]

        vec = await asyncio.to_thread(_embed)
        async with ctx.db.sessionmaker() as s:
            asset = await s.get(Asset, asset_id)
            if asset is not None:
                asset.image_embedding = vec
                await s.commit()
        return {"model": embedder.name, "dim": int(vec.shape[0])}


@register
class Reconstruct3dHandler(Handler):
    type = "reconstruct3d"
    blocking = False
    result_model = ReconstructResult

    def runs_locally(self, ctx: JobContext) -> bool:
        return False

    async def apply(self, ctx: JobContext, session: Any, job: Job, result: dict[str, Any]) -> None:
        site_id = int(job.payload["site_id"])
        if await session.get(Site, site_id) is None:
            return
        key = result["artifact_key"]
        if not key.startswith(f"twins/site-{site_id}/job-{job.id}/"):
            raise InvalidResultError("artifact_key does not belong to this job")
        if not await ctx.storage.exists(key):
            raise InvalidResultError("artifact was not uploaded")
        sources = result["source_asset_ids"] or [int(i["asset_id"]) for i in job.payload.get("images", [])]
        noun = "photo" if len(sources) == 1 else "photos"
        default_title = f"{result['method'].replace('-', ' ').capitalize()} from {len(sources)} {noun}"
        session.add(
            Twin(
                site_id=site_id,
                title=job.payload.get("title") or result["title"] or default_title,
                method=result["method"],
                format=result["format"],
                storage_key=key,
                point_count=result["point_count"],
                source_asset_ids=sources,
                meta={"job_id": job.id, "provenance": "gpu-worker"},
            )
        )
