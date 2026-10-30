"""Hybrid, cross-script retrieval.

Three independent signals are fused with Reciprocal Rank Fusion (Cormack et al., 2009):

* **keyword**  - full-text match on the original text *and* its English translation;
* **phonetic** - match on script-agnostic phonetic keys, so "rani ki vav", "रानी की वाव" and
  "રાણી કી વાવ" retrieve each other (and spelling variants such as "Rani ki Vav" / "Raani-ki-vaav");
* **semantic** - multilingual MiniLM embeddings (Hindi/Gujarati/English in one space).

Backends: PostgreSQL uses a GIN tsvector index and pgvector HNSW; SQLite (dev / single box) uses an
in-memory BM25 index and a NumPy matrix, rebuilt lazily when the corpus signature changes.
Sites (name + semantics) and photos (CLIP text-to-image) are retrieved alongside passages.
"""

from __future__ import annotations

import asyncio
import difflib
import heapq
import math
import time
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

import numpy as np
from sqlalchemy import ColumnClause, Float, String, Text, cast, desc, func, literal, literal_column, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.models import Asset, AssetKind, Chunk, Site, chunk_fts_sql
from app.schemas.search import (
    AssetBrief,
    PhotoHit,
    QueryInterpretation,
    SearchHit,
    SearchResponse,
    SiteHit,
    Snippet,
)
from app.services.embeddings import get_image_embedder, get_text_embedder
from app.services.text.entities import static_places
from app.services.text.phonetic import phonetic_key
from app.services.text.scripts import WORD_RE, detect_language

FTS_EXPR = chunk_fts_sql("chunks")  # must stay identical to the `ix_chunks_fts` GIN index expression
CANDIDATES = 80
MIN_TERM = 2
HIGHLIGHT_MIN = 3
SNIPPET_CHARS = 300
SITE_MIN_SCORE = 0.42


# ---------------------------------------------------------------- query model
@dataclass(slots=True)
class SearchFilters:
    language: str | None = None
    kinds: list[str] = field(default_factory=list)
    site_id: int | None = None
    journey_id: int | None = None
    category: str | None = None
    era_from: int | None = None
    era_to: int | None = None
    bbox: tuple[float, float, float, float] | None = None  # west, south, east, north

    def asset_conditions(self) -> list[Any]:
        conds: list[Any] = []
        if self.kinds:
            conds.append(Asset.kind.in_(self.kinds))
        if self.site_id is not None:
            conds.append(Asset.site_id == self.site_id)
        if self.journey_id is not None:
            conds.append(Asset.journey_id == self.journey_id)
        if self.category:
            conds.append(Asset.site_id.in_(select(Site.id).where(Site.category == self.category)))
        if self.era_from is not None:
            conds.append(Asset.era_year >= self.era_from)
        if self.era_to is not None:
            conds.append(Asset.era_year <= self.era_to)
        if self.bbox is not None:
            w, s, e, n = self.bbox
            conds += [Asset.lat.between(s, n), Asset.lon.between(w, e)]
        return conds

    def chunk_conditions(self) -> list[Any]:
        conds = self.asset_conditions()
        if self.language:
            conds.append(Chunk.language == self.language)
        return conds


@dataclass(slots=True)
class QueryTerms:
    raw: list[str]
    phonetic: list[str]

    @classmethod
    def parse(cls, q: str) -> QueryTerms:
        raw = list(dict.fromkeys(t.lower() for t in WORD_RE.findall(q) if len(t) >= MIN_TERM))
        phon = list(dict.fromkeys(w for w in phonetic_key(q).split() if len(w) >= MIN_TERM))
        return cls(raw, phon)

    @property
    def all(self) -> list[str]:
        return list(dict.fromkeys([*self.raw, *self.phonetic]))


@lru_cache(maxsize=50_000)
def _token_key(token: str) -> str:
    return phonetic_key(token)


def doc_tokens(text: str, translation: str | None, phonetic: str | None) -> list[str]:
    toks = [t.lower() for t in WORD_RE.findall(text)]
    if translation:
        toks += [t.lower() for t in WORD_RE.findall(translation)]
    if phonetic:
        toks += phonetic.split()
    return [t for t in toks if len(t) >= MIN_TERM]


# ---------------------------------------------------------------- BM25 (SQLite backend)
class Bm25:
    k1, b = 1.4, 0.75

    def __init__(self, docs: Sequence[list[str]]) -> None:
        self.n = len(docs)
        self.lens = np.array([len(d) for d in docs], dtype=np.float32)
        self.avgdl = float(self.lens.mean()) if self.n else 1.0
        self.postings: dict[str, list[tuple[int, int]]] = defaultdict(list)
        for i, d in enumerate(docs):
            for tok, tf in Counter(d).items():
                self.postings[tok].append((i, tf))

    def search(self, terms: Sequence[str], k: int, allowed: np.ndarray | None = None) -> list[tuple[int, float]]:
        scores: dict[int, float] = defaultdict(float)
        for t in set(terms):
            plist = self.postings.get(t)
            if not plist:
                continue
            idf = math.log(1 + (self.n - len(plist) + 0.5) / (len(plist) + 0.5))
            for i, tf in plist:
                norm = tf + self.k1 * (1 - self.b + self.b * self.lens[i] / self.avgdl)
                scores[i] += idf * tf * (self.k1 + 1) / norm
        items = ((i, s) for i, s in scores.items() if allowed is None or allowed[i])
        return heapq.nlargest(k, items, key=lambda x: x[1])


@dataclass(slots=True)
class _ChunkIndex:
    signature: tuple[Any, ...]
    ids: np.ndarray
    bm25: Bm25
    matrix: np.ndarray


@dataclass(slots=True)
class _ImageIndex:
    signature: tuple[Any, ...]
    ids: np.ndarray
    matrix: np.ndarray


@dataclass(slots=True)
class _SiteRow:
    id: int
    slug: str
    name: str
    name_native: str | None
    category: str
    lat: float
    lon: float
    keys: list[str]
    embedding: np.ndarray | None


def _stack(vectors: list[Any], dim: int) -> np.ndarray:
    if not vectors:
        return np.zeros((0, dim), dtype=np.float32)
    return np.stack([v if v is not None else np.zeros(dim, dtype=np.float32) for v in vectors]).astype(np.float32)


def _top_k(matrix: np.ndarray, q: np.ndarray, k: int, allowed: np.ndarray | None) -> list[tuple[int, float]]:
    if matrix.shape[0] == 0:
        return []
    sims = matrix @ q
    if allowed is not None:
        sims = np.where(allowed, sims, -np.inf)
    k = min(k, sims.shape[0])
    idx = np.argpartition(-sims, k - 1)[:k]
    idx = idx[np.argsort(-sims[idx])]
    return [(int(i), float(sims[i])) for i in idx if np.isfinite(sims[i])]


def _pg_vector(vec: np.ndarray) -> Any:
    from pgvector.sqlalchemy import VECTOR

    lit = "[" + ",".join(f"{x:.6f}" for x in vec.tolist()) + "]"
    return cast(cast(literal(lit, String), Text), VECTOR(len(vec)))


# ---------------------------------------------------------------- snippets
def make_snippet(text: str, raw: set[str], phon: set[str], width: int = SNIPPET_CHARS) -> Snippet:
    spans: list[tuple[int, int]] = []
    for m in WORD_RE.finditer(text):
        tok = m.group()
        low = tok.lower()
        if len(low) < HIGHLIGHT_MIN and len(tok) < HIGHLIGHT_MIN:
            continue
        if low in raw or (phon and _token_key(tok) in phon):
            spans.append((m.start(), m.end()))
    if len(text) <= width:
        return Snippet(text=text, highlights=spans)
    anchor = spans[0][0] if spans else 0
    start = max(0, anchor - width // 4)
    if start:
        ws = text.rfind(" ", 0, start)
        start = ws + 1 if ws >= 0 and start - ws < 40 else start
    end = min(len(text), start + width)
    if end < len(text):
        ws = text.rfind(" ", start, end)
        end = ws if ws > start + width // 2 else end
    rel = [(s - start, e - start) for s, e in spans if s >= start and e <= end]
    return Snippet(text=text[start:end], highlights=rel, prefix_ellipsis=start > 0, suffix_ellipsis=end < len(text))


def asset_brief(asset: Asset, site: Site | None) -> AssetBrief:
    return AssetBrief(
        id=asset.id,
        kind=asset.kind,
        title=asset.title,
        status=asset.status,
        thumb_url=f"/api/v1/assets/{asset.id}/thumbnail" if asset.thumb_key else None,
        language=asset.language,
        site_id=asset.site_id,
        site_name=site.name if site else None,
        site_slug=site.slug if site else None,
        era_year=asset.era_year,
        lat=asset.lat,
        lon=asset.lon,
    )


# ---------------------------------------------------------------- service
class SearchService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._chunks: _ChunkIndex | None = None
        self._images: _ImageIndex | None = None
        self._sites: tuple[tuple[Any, ...], list[_SiteRow]] | None = None
        self._lock = asyncio.Lock()

    def invalidate(self) -> None:
        self._chunks = self._images = self._sites = None

    async def search(
        self, session: AsyncSession, q: str, filters: SearchFilters | None = None, *, limit: int = 20, offset: int = 0
    ) -> SearchResponse:
        t0 = time.perf_counter()
        filters = filters or SearchFilters()
        terms = QueryTerms.parse(q)
        lang, script = detect_language(q)
        embedder = get_text_embedder(self.settings)
        qvec = await asyncio.to_thread(embedder.embed_query, q)
        pg = session.bind is not None and session.bind.dialect.name == "postgresql"

        if pg:
            lexical = await self._pg_lexical(session, terms, filters)
            semantic = await self._pg_semantic(session, qvec, filters)
        else:
            idx = await self._chunk_index(session)
            allowed = await self._allowed_mask(session, idx.ids, filters)
            lexical = [(int(idx.ids[i]), s) for i, s in idx.bm25.search(terms.all, CANDIDATES, allowed)]
            semantic = [(int(idx.ids[i]), s) for i, s in _top_k(idx.matrix, qvec, CANDIDATES, allowed)]
        semantic = [(cid, s) for cid, s in semantic if s >= self.settings.semantic_min_score]

        k = self.settings.rrf_k
        fused: dict[int, float] = defaultdict(float)
        for ranked in (lexical, semantic):
            for rank, (cid, _) in enumerate(ranked):
                fused[cid] += 1.0 / (k + rank + 1)
        semantic_ids = {cid for cid, _ in semantic}
        order = sorted(fused, key=lambda c: -fused[c])

        hits, total, facets = await self._hydrate(session, order, fused, semantic_ids, terms, limit, offset)
        sites = await self._site_hits(session, terms, qvec, filters)
        photos = await self._photo_hits(session, q, script, filters)
        suggestions = [] if hits or sites else await self._suggest(session, q)
        return SearchResponse(
            query=q,
            interpreted=QueryInterpretation(
                script=script, language=lang, phonetic=" ".join(terms.phonetic), terms=terms.raw
            ),
            total=total,
            hits=hits,
            sites=sites,
            photos=photos,
            facets=facets,
            suggestions=suggestions,
            took_ms=round((time.perf_counter() - t0) * 1000, 1),
            backend="postgres" if pg else "sqlite",
            embedder=embedder.name,
        )

    # ------------------------------------------------------------ PostgreSQL
    async def _pg_lexical(self, s: AsyncSession, terms: QueryTerms, f: SearchFilters) -> list[tuple[int, float]]:
        if not terms.all:
            return []
        tsq_text = " | ".join(f"{t}:*" if len(t) >= 4 else t for t in terms.all)
        tsv: ColumnClause[Any] = literal_column(FTS_EXPR)
        tsq = func.to_tsquery(literal_column("'simple'"), literal(tsq_text, String))
        rank = func.ts_rank_cd(tsv, tsq)
        stmt = (
            select(Chunk.id, rank.label("r"))
            .join(Asset, Asset.id == Chunk.asset_id)
            .where(tsv.op("@@")(tsq), *f.chunk_conditions())
            .order_by(desc("r"))
            .limit(CANDIDATES)
        )
        return [(int(i), float(r)) for i, r in (await s.execute(stmt)).all()]

    async def _pg_semantic(self, s: AsyncSession, qvec: np.ndarray, f: SearchFilters) -> list[tuple[int, float]]:
        dist = Chunk.embedding.op("<=>", return_type=Float)(_pg_vector(qvec))
        stmt = (
            select(Chunk.id, dist.label("d"))
            .join(Asset, Asset.id == Chunk.asset_id)
            .where(Chunk.embedding.is_not(None), *f.chunk_conditions())
            .order_by(dist)
            .limit(CANDIDATES)
        )
        return [(int(i), 1.0 - float(d)) for i, d in (await s.execute(stmt)).all()]

    # ------------------------------------------------------------ SQLite / in-memory
    async def _chunk_index(self, s: AsyncSession) -> _ChunkIndex:
        # Chunks are only ever replaced wholesale (delete + insert on re-index). SQLite reuses the
        # highest rowid after a delete, so count/max(id) alone can miss a re-index; created_at cannot.
        sig = tuple(
            (await s.execute(select(func.count(Chunk.id), func.max(Chunk.id), func.max(Chunk.created_at)))).one()
        )
        if self._chunks is not None and self._chunks.signature == sig:
            return self._chunks
        async with self._lock:
            if self._chunks is not None and self._chunks.signature == sig:
                return self._chunks
            rows = (
                await s.execute(
                    select(Chunk.id, Chunk.text, Chunk.translation, Chunk.phonetic, Chunk.embedding).order_by(Chunk.id)
                )
            ).all()

            def build() -> _ChunkIndex:
                ids = np.array([r[0] for r in rows], dtype=np.int64)
                bm25 = Bm25([doc_tokens(r[1], r[2], r[3]) for r in rows])
                return _ChunkIndex(sig, ids, bm25, _stack([r[4] for r in rows], self.settings.embed_dim))

            self._chunks = await asyncio.to_thread(build)
            return self._chunks

    @staticmethod
    async def _allowed_mask(s: AsyncSession, ids: np.ndarray, f: SearchFilters) -> np.ndarray | None:
        conds = f.chunk_conditions()
        if not conds:
            return None
        allowed = (await s.scalars(select(Chunk.id).join(Asset, Asset.id == Chunk.asset_id).where(*conds))).all()
        return np.isin(ids, np.fromiter(allowed, dtype=np.int64, count=len(allowed)))

    # ------------------------------------------------------------ hydration
    async def _hydrate(
        self,
        s: AsyncSession,
        order: list[int],
        fused: dict[int, float],
        semantic_ids: set[int],
        terms: QueryTerms,
        limit: int,
        offset: int,
    ) -> tuple[list[SearchHit], int, dict[str, dict[str, int]]]:
        if not order:
            return [], 0, {"kind": {}, "language": {}}
        meta = {
            cid: (aid, lang, kind)
            for cid, aid, lang, kind in (
                await s.execute(
                    select(Chunk.id, Chunk.asset_id, Chunk.language, Asset.kind)
                    .join(Asset, Asset.id == Chunk.asset_id)
                    .where(Chunk.id.in_(order))
                )
            ).all()
        }
        best: dict[int, int] = {}
        extra: Counter[int] = Counter()
        for cid in order:
            if cid not in meta:
                continue
            aid = meta[cid][0]
            if aid in best:
                extra[aid] += 1
            else:
                best[aid] = cid
        collapsed = list(best.values())
        facets = {
            "kind": dict(Counter(meta[c][2] for c in collapsed)),
            "language": dict(Counter(meta[c][1] or "und" for c in collapsed)),
        }
        page = collapsed[offset : offset + limit]
        if not page:
            return [], len(collapsed), facets
        rows = (
            await s.execute(
                select(Chunk, Asset, Site)
                .join(Asset, Asset.id == Chunk.asset_id)
                .outerjoin(Site, Site.id == Asset.site_id)
                .where(Chunk.id.in_(page))
            )
        ).all()
        by_id = {c.id: (c, a, site) for c, a, site in rows}
        raw, phon = set(terms.raw), set(terms.phonetic)
        top = 2.0 / (self.settings.rrf_k + 1)
        hits: list[SearchHit] = []
        for cid in page:
            if cid not in by_id:
                continue
            chunk, asset, site = by_id[cid]
            hits.append(
                SearchHit(
                    chunk_id=cid,
                    page_no=chunk.page_no,
                    score=round(min(1.0, fused[cid] / top), 4),
                    matched_by=self._explain(chunk, cid in semantic_ids, raw, phon),
                    language=chunk.language,
                    snippet=make_snippet(chunk.text, raw, phon),
                    translation=make_snippet(chunk.translation, raw, phon) if chunk.translation else None,
                    translation_engine=chunk.translation_engine,
                    more_in_asset=extra[asset.id],
                    asset=asset_brief(asset, site),
                )
            )
        return hits, len(collapsed), facets

    @staticmethod
    def _explain(chunk: Chunk, semantic: bool, raw: set[str], phon: set[str]) -> list[str]:
        why: list[str] = []
        text_toks = {t.lower() for t in WORD_RE.findall(chunk.text)}
        tr_toks = {t.lower() for t in WORD_RE.findall(chunk.translation or "")}
        significant = {t for t in raw if len(t) >= HIGHLIGHT_MIN}
        if significant & (text_toks | tr_toks):
            why.append("keyword")
        phon_hit = {t for t in phon if len(t) >= HIGHLIGHT_MIN} & set((chunk.phonetic or "").split())
        if phon_hit and not (significant & text_toks):
            why.append("phonetic")  # matched across scripts / spellings, not verbatim
        if semantic:
            why.append("semantic")
        return why or ["keyword"]

    # ------------------------------------------------------------ sites
    async def _site_rows(self, s: AsyncSession) -> list[_SiteRow]:
        sig = tuple((await s.execute(select(func.count(Site.id), func.max(Site.updated_at)))).one())
        if self._sites is not None and self._sites[0] == sig:
            return self._sites[1]
        rows = (await s.scalars(select(Site))).all()
        out = [
            _SiteRow(
                r.id,
                r.slug,
                r.name,
                r.name_native,
                r.category,
                r.lat,
                r.lon,
                [k.strip() for k in (r.phonetic or "").split("|") if k.strip()],
                r.embedding,
            )
            for r in rows
        ]
        self._sites = (sig, out)
        return out

    async def _site_hits(self, s: AsyncSession, terms: QueryTerms, qvec: np.ndarray, f: SearchFilters) -> list[SiteHit]:
        qkey = " ".join(terms.phonetic)
        qset = {t for t in terms.phonetic if len(t) >= HIGHLIGHT_MIN}
        hits: list[SiteHit] = []
        for r in await self._site_rows(s):
            if f.category and r.category != f.category:
                continue
            if f.bbox and not (f.bbox[1] <= r.lat <= f.bbox[3] and f.bbox[0] <= r.lon <= f.bbox[2]):
                continue
            name_score = 0.0
            for key in r.keys:
                if qkey and (key == qkey):
                    name_score = 1.0
                elif qkey and (f" {key} " in f" {qkey} " or f" {qkey} " in f" {key} "):
                    name_score = max(name_score, 0.85)
                else:
                    kset = {t for t in key.split() if len(t) >= HIGHLIGHT_MIN}
                    if kset and qset:
                        name_score = max(name_score, 0.7 * len(kset & qset) / len(kset))
            sem = float(r.embedding @ qvec) if r.embedding is not None else 0.0
            score = max(name_score, sem)
            if score >= SITE_MIN_SCORE:
                hits.append(
                    SiteHit(
                        id=r.id,
                        slug=r.slug,
                        name=r.name,
                        name_native=r.name_native,
                        category=r.category,
                        lat=r.lat,
                        lon=r.lon,
                        score=round(score, 4),
                        reason="name" if name_score >= sem else "semantic",
                    )
                )
        return sorted(hits, key=lambda h: -h.score)[:6]

    # ------------------------------------------------------------ photos (CLIP)
    async def _photo_hits(self, s: AsyncSession, q: str, script: str | None, f: SearchFilters) -> list[PhotoHit]:
        if script not in (None, "Latn") or not self.settings.enable_image_search:
            return []  # CLIP's text tower is English-only
        if f.kinds and not {AssetKind.photo, AssetKind.scan} & set(f.kinds):
            return []
        embedder = await asyncio.to_thread(get_image_embedder, self.settings)
        if embedder is None:
            return []
        qv = await asyncio.to_thread(embedder.embed_query, q)
        conds = [Asset.image_embedding.is_not(None), *f.asset_conditions()]
        if s.bind is not None and s.bind.dialect.name == "postgresql":
            dist = Asset.image_embedding.op("<=>", return_type=Float)(_pg_vector(qv))
            ranked = [
                (int(i), 1.0 - float(d))
                for i, d in (await s.execute(select(Asset.id, dist).where(*conds).order_by(dist).limit(12))).all()
            ]
        else:
            idx = await self._image_index(s)
            allowed = None
            if f.asset_conditions():
                ok = (await s.scalars(select(Asset.id).where(*conds))).all()
                allowed = np.isin(idx.ids, np.array(ok, dtype=np.int64))
            ranked = [(int(idx.ids[i]), sc) for i, sc in _top_k(idx.matrix, qv, 12, allowed)]
        ranked = [(i, sc) for i, sc in ranked if sc >= self.settings.clip_min_score]
        if not ranked:
            return []
        rows = (
            await s.execute(
                select(Asset, Site)
                .outerjoin(Site, Site.id == Asset.site_id)
                .where(Asset.id.in_([i for i, _ in ranked]))
            )
        ).all()
        by_id = {a.id: (a, site) for a, site in rows}
        return [PhotoHit(score=round(sc, 4), asset=asset_brief(*by_id[i])) for i, sc in ranked if i in by_id]

    async def _image_index(self, s: AsyncSession) -> _ImageIndex:
        sig = tuple(
            (
                await s.execute(
                    select(func.count(Asset.id), func.max(Asset.updated_at)).where(Asset.image_embedding.is_not(None))
                )
            ).one()
        )
        if self._images is not None and self._images.signature == sig:
            return self._images
        rows = (
            await s.execute(select(Asset.id, Asset.image_embedding).where(Asset.image_embedding.is_not(None)))
        ).all()
        self._images = _ImageIndex(
            sig,
            np.array([r[0] for r in rows], dtype=np.int64),
            _stack([r[1] for r in rows], self.settings.image_embed_dim),
        )
        return self._images

    # ------------------------------------------------------------ did-you-mean
    async def _suggest(self, s: AsyncSession, q: str) -> list[str]:
        names = {r.name for r in await self._site_rows(s)} | {p.name for p in static_places()}
        by_key = {phonetic_key(n): n for n in names}
        close = difflib.get_close_matches(phonetic_key(q), list(by_key), n=3, cutoff=0.6)
        return [by_key[c] for c in close]
