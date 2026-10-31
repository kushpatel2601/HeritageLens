"""Pluggable embedding providers.

* `FastEmbedTextEmbedder`  - multilingual MiniLM via ONNX Runtime (CPU, no torch); 50+ languages
  including Hindi, Gujarati, Marathi share one vector space with English.
* `LeanTextEmbedder`       - the same model and vectors in a third of the memory, for 512 MB hosts
  (see `app.services.lean_embedder`).
* `HashingEmbedder`        - dependency-free deterministic fallback (char n-grams over phonetic keys),
  so the system degrades gracefully offline and tests stay hermetic.
* `ClipImageEmbedder`      - CLIP ViT-B/32 image + text towers for "describe the photo" search.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import zlib
from functools import lru_cache
from typing import Protocol

import numpy as np

from app.core.config import BACKEND_DIR, Settings, get_settings
from app.services.text.phonetic import phonetic_key

log = logging.getLogger(__name__)
MODEL_CACHE_DIR = BACKEND_DIR / "var" / "models"


def _normalise(mat: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return (mat / norms).astype(np.float32)


class TextEmbedder(Protocol):
    name: str
    dim: int

    def embed(self, texts: list[str]) -> np.ndarray: ...
    def embed_query(self, text: str) -> np.ndarray: ...


class HashingEmbedder:
    def __init__(self, dim: int = 384) -> None:
        self.dim = dim
        self.name = f"hashing-ngram-{dim}"

    def _vec(self, text: str) -> np.ndarray:
        v = np.zeros(self.dim, dtype=np.float32)
        key = phonetic_key(text)
        feats: list[str] = key.split()
        padded = f" {key} "
        feats += [padded[i : i + 3] for i in range(len(padded) - 2)]
        feats += [padded[i : i + 4] for i in range(len(padded) - 3)]
        for f in feats:
            h = zlib.crc32(f.encode("utf-8"))
            v[h % self.dim] += 1.0 if (h >> 31) & 1 else -1.0
        return v

    def embed(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        return _normalise(np.stack([self._vec(t) for t in texts]))

    def embed_query(self, text: str) -> np.ndarray:
        return self.embed([text])[0]


class FastEmbedTextEmbedder:
    def __init__(self, model: str, dim: int, threads: int = 0) -> None:
        from fastembed import TextEmbedding

        self.name = model
        self.dim = dim
        self._model = TextEmbedding(model_name=model, cache_dir=str(MODEL_CACHE_DIR), threads=threads or None)
        self._lock = threading.Lock()

    def embed(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        with self._lock:
            vecs = list(self._model.embed(texts, batch_size=32))
        return _normalise(np.asarray(vecs, dtype=np.float32))

    def embed_query(self, text: str) -> np.ndarray:
        return self.embed([text])[0]


class ClipImageEmbedder:
    def __init__(self, vision_model: str, text_model: str) -> None:
        from fastembed import ImageEmbedding, TextEmbedding

        self.name = vision_model
        self._vision = ImageEmbedding(model_name=vision_model, cache_dir=str(MODEL_CACHE_DIR))
        self._text = TextEmbedding(model_name=text_model, cache_dir=str(MODEL_CACHE_DIR))
        self._lock = threading.Lock()

    def embed_images(self, paths_or_bytes: list[object]) -> np.ndarray:
        with self._lock:
            # `arg-type` is only reported when fastembed (the `ml` extra) is installed.
            vecs = list(self._vision.embed(paths_or_bytes))  # type: ignore[arg-type, unused-ignore]
        return _normalise(np.asarray(vecs, dtype=np.float32))

    def embed_query(self, text: str) -> np.ndarray:
        with self._lock:
            vec = next(iter(self._text.embed([text])))
        return _normalise(np.asarray([vec], dtype=np.float32))[0]


_text_lock = threading.Lock()
_image_lock = threading.Lock()
_text_embedder: TextEmbedder | None = None
_image_embedder: ClipImageEmbedder | None = None
_image_failed = False


def get_text_embedder(settings: Settings | None = None) -> TextEmbedder:
    """Process-wide singleton. Model download/initialisation happens lazily on first use."""
    global _text_embedder
    if _text_embedder is not None:
        return _text_embedder
    settings = settings or get_settings()
    with _text_lock:
        if _text_embedder is None:
            _text_embedder = _build_text_embedder(settings)
    return _text_embedder


async def aget_text_embedder(settings: Settings | None = None) -> TextEmbedder:
    """`get_text_embedder` for async code: a cold model load (tens of seconds on a 0.1-CPU host) runs in a
    thread instead of stalling the event loop, health checks included."""
    if _text_embedder is not None:
        return _text_embedder
    return await asyncio.to_thread(get_text_embedder, settings)


async def warm_text_embedder(settings: Settings) -> None:
    """Load the text model and run one query so the first real search does not pay the start-up cost."""
    try:
        embedder = await aget_text_embedder(settings)
        await asyncio.to_thread(embedder.embed_query, "warm-up")
        log.info("text embedder warmed up: %s", embedder.name)
    except Exception:
        log.exception("text embedder warm-up failed; it will load on first use")


def _build_text_embedder(settings: Settings) -> TextEmbedder:
    from app.services.lean_embedder import LeanTextEmbedder, is_lean_model_dir

    if settings.embedder == "lean" or (settings.embedder == "auto" and is_lean_model_dir(settings.lean_model_dir)):
        try:
            lean = LeanTextEmbedder(
                settings.lean_model_dir, expected_model=settings.text_embed_model, threads=settings.embed_threads
            )
            log.info("text embedder: %s (lean runtime from %s)", lean.name, settings.lean_model_dir)
            return lean
        except Exception as exc:
            if settings.embedder == "lean":
                raise
            log.warning("lean text model unusable (%s); trying fastembed", exc)
    if settings.embedder in ("auto", "fastembed"):
        try:
            emb = FastEmbedTextEmbedder(settings.text_embed_model, settings.embed_dim, settings.embed_threads)
            log.info("text embedder: %s", emb.name)
            return emb
        except Exception as exc:
            if settings.embedder == "fastembed":
                raise
            log.warning("fastembed unavailable (%s); falling back to hashing embedder", exc)
    return HashingEmbedder(settings.embed_dim)


def get_image_embedder(settings: Settings | None = None) -> ClipImageEmbedder | None:
    global _image_embedder, _image_failed
    settings = settings or get_settings()
    if not settings.enable_image_search or settings.embedder == "hashing" or _image_failed:
        return None
    if _image_embedder is not None:
        return _image_embedder
    with _image_lock:
        if _image_embedder is None and not _image_failed:
            try:
                _image_embedder = ClipImageEmbedder(settings.image_embed_model, settings.image_text_embed_model)
                log.info("image embedder: %s", _image_embedder.name)
            except Exception as exc:
                _image_failed = True
                log.warning("CLIP image search disabled: %s", exc)
    return _image_embedder


def reset_embedders() -> None:
    """Test hook."""
    global _text_embedder, _image_embedder, _image_failed
    _text_embedder, _image_embedder, _image_failed = None, None, False


@lru_cache(maxsize=1024)
def cached_query_vector(text: str) -> bytes:
    return get_text_embedder().embed_query(text).tobytes()
