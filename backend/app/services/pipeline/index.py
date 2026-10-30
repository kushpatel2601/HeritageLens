"""Stage 2 - indexing: chunk -> language/script -> phonetic key -> embedding -> entities -> linking.

Re-indexing is idempotent and cheap, so enrichment stages (OCR, translation, captioning) simply
re-run it. Translations survive re-chunking through a per-asset *translation memory* keyed by the
normalised source text.
"""

from __future__ import annotations

import asyncio
import logging
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from sqlalchemy import delete, func, select

from app.db.models import Asset, AssetKind, AssetStatus, Chunk, Entity, Job, Page, Site
from app.services.embeddings import get_text_embedder
from app.services.pipeline.base import Handler, JobContext, register
from app.services.text.chunking import chunk_text
from app.services.text.entities import Gazetteer, Mention, build_gazetteer, extract_entities
from app.services.text.phonetic import phonetic_key
from app.services.text.scripts import detect_language

log = logging.getLogger(__name__)

TM_KEY = "translation_memory"
_PARA_SPLIT = "\n\n"


def norm(text: str) -> str:
    return " ".join(text.split())


def lookup_translation(text: str, memory: dict[str, list[str]]) -> tuple[str, str] | None:
    """Exact chunk hit, else stitch together paragraph-level hits. Returns (translation, engine).

    An empty translation means "already attempted" and is returned too so it is not re-requested.
    """
    hit = memory.get(norm(text))
    if hit is not None:
        return hit[0], hit[1]
    paras = [p for p in text.split(_PARA_SPLIT) if p.strip()]
    if len(paras) > 1 and all(norm(p) in memory for p in paras):
        parts = [memory[norm(p)] for p in paras]
        return _PARA_SPLIT.join(t for t, _ in parts), parts[0][1]
    return None


# ---------------------------------------------------------------- gazetteer cache
_gaz_cache: tuple[tuple[int, Any], Gazetteer] | None = None
_gaz_lock = asyncio.Lock()


async def load_gazetteer(session: Any) -> Gazetteer:
    """Sites + static places, rebuilt only when the sites table changes."""
    global _gaz_cache
    sig = tuple((await session.execute(select(func.count(Site.id), func.max(Site.updated_at)))).one())
    if _gaz_cache is not None and _gaz_cache[0] == sig:
        return _gaz_cache[1]
    async with _gaz_lock:
        rows = (
            await session.execute(select(Site.id, Site.name, Site.name_native, Site.alt_names, Site.lat, Site.lon))
        ).all()
        sites = [
            (sid, name, [name, *([native] if native else []), *(alts or [])], lat, lon)
            for sid, name, native, alts, lat, lon in rows
        ]
        gaz = build_gazetteer(sites)
        _gaz_cache = (sig, gaz)
        return gaz


def reset_gazetteer_cache() -> None:
    global _gaz_cache
    _gaz_cache = None


# ---------------------------------------------------------------- indexing
@dataclass(slots=True)
class ChunkDraft:
    page_no: int
    seq: int
    start: int
    text: str
    language: str | None
    script: str | None
    phonetic: str
    translation: str | None = None
    translation_engine: str | None = None
    tm_hit: bool = False  # translation memory knows this chunk (possibly as an empty "attempted" entry)
    mentions: list[Mention] = field(default_factory=list)
    vector: np.ndarray | None = None


def build_chunks(
    sources: list[tuple[int, str]],
    memory: dict[str, list[str]],
    gazetteer: Gazetteer,
    max_chars: int,
    overlap: int,
) -> list[ChunkDraft]:
    drafts: list[ChunkDraft] = []
    for page_no, text in sources:
        for c in chunk_text(text, max_chars, overlap):
            lang, script = detect_language(c.text)
            d = ChunkDraft(page_no, c.seq, c.start, c.text, lang, script, phonetic_key(c.text))
            hit = None
            if lang not in (None, "en") and memory:
                # Worker translations are keyed by the full chunk; curated ones by paragraph (the body).
                hit = lookup_translation(c.text, memory) or lookup_translation(c.body, memory)
            d.tm_hit = hit is not None
            if hit is not None and hit[0]:
                d.translation, d.translation_engine = hit
            d.mentions = extract_entities(c.text, gazetteer)
            drafts.append(d)
    return drafts


def embed_chunks(drafts: list[ChunkDraft]) -> str:
    """Original text and its English translation are embedded separately and averaged, so both
    native-script and English queries land close to the passage (and MiniLM's 128-token window
    is not wasted on a concatenation)."""
    embedder = get_text_embedder()
    if not drafts:
        return embedder.name
    base = embedder.embed([d.text for d in drafts])
    with_tr = [i for i, d in enumerate(drafts) if d.translation]
    if with_tr:
        tr = embedder.embed([drafts[i].translation or "" for i in with_tr])
        mixed = base[with_tr] + tr
        base[with_tr] = mixed / np.maximum(np.linalg.norm(mixed, axis=1, keepdims=True), 1e-12)
    for d, v in zip(drafts, base, strict=True):
        d.vector = v.astype(np.float32)
    return embedder.name


@register
class IndexHandler(Handler):
    type = "index"

    async def run(self, ctx: JobContext, job: Job) -> dict[str, Any]:
        asset_id = int(job.payload["asset_id"])
        async with ctx.db.sessionmaker() as s:
            asset = await s.get(Asset, asset_id)
            if asset is None:
                return {"skipped": "asset deleted"}
            pages = (await s.scalars(select(Page).where(Page.asset_id == asset_id).order_by(Page.page_no))).all()
            site_name = (await s.get(Site, asset.site_id)).name if asset.site_id else None  # type: ignore[union-attr]
            gazetteer = await load_gazetteer(s)
            await s.commit()

        sources = self._sources(asset, list(pages), site_name)
        memory: dict[str, list[str]] = dict((asset.meta or {}).get(TM_KEY, {}))
        settings = ctx.settings
        drafts = await asyncio.to_thread(
            build_chunks, sources, memory, gazetteer, settings.chunk_chars, settings.chunk_overlap
        )
        model = await asyncio.to_thread(embed_chunks, drafts)

        async with ctx.db.sessionmaker() as s:
            asset = await s.get(Asset, asset_id)
            if asset is None:
                return {"skipped": "asset deleted"}
            await s.execute(delete(Entity).where(Entity.asset_id == asset_id))
            await s.execute(delete(Chunk).where(Chunk.asset_id == asset_id))
            rows: list[tuple[ChunkDraft, Chunk]] = []
            for d in drafts:
                row = Chunk(
                    asset_id=asset_id,
                    page_no=d.page_no,
                    seq=d.seq,
                    char_start=d.start,
                    text=d.text,
                    language=d.language,
                    script=d.script,
                    translation=d.translation,
                    translation_engine=d.translation_engine,
                    phonetic=d.phonetic,
                    embedding=d.vector,
                    embed_model=model,
                )
                s.add(row)
                rows.append((d, row))
            await s.flush()
            for d, row in rows:
                for m in d.mentions:
                    s.add(
                        Entity(
                            asset_id=asset_id,
                            chunk_id=row.id,
                            kind=m.kind,
                            surface=m.surface[:200],
                            normalized=m.normalized[:200],
                            site_id=m.site_id,
                            lat=m.lat,
                            lon=m.lon,
                            year=m.year,
                            start=m.start,
                            end=m.end,
                        )
                    )
            self._derive_asset_facts(asset, drafts)
            asset.status, asset.error = AssetStatus.ready, None
            pending = await self._enqueue_enrichment(ctx, s, asset, rows)
            await s.commit()
        return {
            "chunks": len(drafts),
            "entities": sum(len(d.mentions) for d in drafts),
            "embed_model": model,
            "enqueued": pending,
        }

    @staticmethod
    def _sources(asset: Asset, pages: list[Page], site_name: str | None) -> list[tuple[int, str]]:
        if asset.kind == AssetKind.photo:
            ctx = (asset.meta or {}).get("context")
            parts: list[str] = []
            seen: set[str] = set()
            # Contributors often repeat the title as the caption; index each distinct line once.
            for part in (asset.title, asset.caption, ctx, f"Site: {site_name}" if site_name else None):
                text = (part or "").strip()
                key = " ".join(text.split()).casefold()
                if key and key not in seen:
                    seen.add(key)
                    parts.append(text)
            return [(1, "\n\n".join(parts))]
        return [(p.page_no, p.text) for p in pages if p.text and p.text.strip()]

    @staticmethod
    def _derive_asset_facts(asset: Asset, drafts: list[ChunkDraft]) -> None:
        langs = Counter(d.language for d in drafts if d.language)
        if langs and not asset.language:
            asset.language = langs.most_common(1)[0][0]
        mentions = [m for d in drafts for m in d.mentions]
        site_votes = Counter(m.site_id for m in mentions if m.site_id is not None)
        if asset.site_id is None and site_votes:
            asset.site_id = site_votes.most_common(1)[0][0]
            asset.meta = {
                **(asset.meta or {}),
                "site_link": {"method": "text", "mentions": site_votes.most_common(1)[0][1]},
            }
        if asset.lat is None:
            geo = next(
                (m for m in mentions if m.kind == "site" and m.site_id == asset.site_id and m.lat is not None), None
            )
            geo = geo or next((m for m in mentions if m.lat is not None), None)
            if geo is not None:
                asset.lat, asset.lon, asset.geo_source = geo.lat, geo.lon, "entity"
        years = [m.year for m in mentions if m.year is not None and m.year <= 2100]
        if asset.era_year is None and years:
            asset.era_year = min(years)

    @staticmethod
    async def _enqueue_enrichment(
        ctx: JobContext, s: Any, asset: Asset, rows: list[tuple[ChunkDraft, Chunk]]
    ) -> list[str]:
        pending: list[str] = []
        todo = [
            {"chunk_id": row.id, "text": d.text, "lang": d.language}
            for d, row in rows
            if d.language not in (None, "en") and not d.tm_hit
        ]
        if todo:
            src = Counter(i["lang"] for i in todo).most_common(1)[0][0]
            await ctx.queue.enqueue(
                s,
                "translate",
                {"asset_id": asset.id, "src_lang": src, "items": todo},
                asset_id=asset.id,
                priority=120,
                dedupe_key=f"translate:{asset.id}",
            )
            pending.append("translate")
        settings = ctx.settings
        is_image = asset.kind in (AssetKind.photo, AssetKind.scan)
        if (
            is_image
            and settings.enable_image_search
            and settings.embedder != "hashing"
            and asset.image_embedding is None
        ):
            await ctx.queue.enqueue(
                s,
                "image_embed",
                {"asset_id": asset.id},
                asset_id=asset.id,
                priority=130,
                dedupe_key=f"image_embed:{asset.id}",
            )
            pending.append("image_embed")
        if asset.kind == AssetKind.photo and settings.enable_captions and not asset.caption:
            await ctx.queue.enqueue(
                s,
                "caption",
                {"asset_id": asset.id, "image_key": asset.thumb_key or asset.storage_key},
                asset_id=asset.id,
                priority=140,
                dedupe_key=f"caption:{asset.id}",
            )
            pending.append("caption")
        return pending
