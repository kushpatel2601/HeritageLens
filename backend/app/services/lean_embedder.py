"""Memory-lean runtime for the multilingual MiniLM text embedder.

Loaded through fastembed, `paraphrase-multilingual-MiniLM-L12-v2` keeps ~500 MB resident: ~250 MB is the
`tokenizers` trie for its 250k-token XLM-R vocabulary, and the fp16 word-embedding table is ~75% of the
weights. That alone breaks 512 MB hosts. `python -m app.cli export-lean-model` rewrites the *same* model
into a directory this module serves in ~170 MB:

* `encoder.onnx`            the transformer with the word-embedding lookup cut out; it reads `inputs_embeds`.
* `word_embeddings.npy`     the fp16 [vocab, dim] table, memory-mapped. A query touches ~20 rows, so only a
                            few pages are ever resident, and the kernel can drop them under pressure.
* `sentencepiece.bpe.model` the original SentencePiece model (compact double-array trie, ~45 MB resident).
* `manifest.json`           the ids and limits that reproduce the reference tokenizer exactly.

The export verifies token ids and vectors against fastembed before it writes anything, so the vectors
already stored in the index stay valid and either backend can serve the same database.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np

MANIFEST_FILE = "manifest.json"
ENCODER_FILE = "encoder.onnx"
TABLE_FILE = "word_embeddings.npy"
SPM_FILE = "sentencepiece.bpe.model"
EMBEDS_INPUT = "inputs_embeds"
FORMAT_VERSION = 1


@dataclass(frozen=True)
class LeanManifest:
    model: str
    dim: int
    max_length: int  # including the two special tokens
    bos_id: int
    eos_id: int
    pad_id: int
    unk_id: int
    id_offset: int  # model id = SentencePiece id + offset (fairseq / XLM-R convention)
    format: int = FORMAT_VERSION

    @classmethod
    def load(cls, model_dir: Path) -> LeanManifest:
        data: dict[str, Any] = json.loads((model_dir / MANIFEST_FILE).read_text(encoding="utf-8"))
        if data.get("format") != FORMAT_VERSION:
            raise ValueError(f"unsupported lean model format {data.get('format')!r} in {model_dir}")
        return cls(**data)

    def save(self, model_dir: Path) -> None:
        (model_dir / MANIFEST_FILE).write_text(json.dumps(asdict(self), indent=2) + "\n", encoding="utf-8")


def is_lean_model_dir(model_dir: Path) -> bool:
    return all((model_dir / f).is_file() for f in (MANIFEST_FILE, ENCODER_FILE, TABLE_FILE, SPM_FILE))


def to_model_ids(piece_ids: Sequence[int], manifest: LeanManifest) -> list[int]:
    """Map SentencePiece ids to model ids the way XLM-R tokenizers do, then add <s> ... </s>.

    SentencePiece id 0 is its own <unk>; every other id is shifted by `id_offset` because fairseq put
    <s>, <pad>, </s>, <unk> first. Truncation keeps the head of the text, like the reference tokenizer.
    """
    body = [i + manifest.id_offset if i else manifest.unk_id for i in piece_ids]
    return [manifest.bos_id, *body[: manifest.max_length - 2], manifest.eos_id]


def pad_batch(rows: Sequence[Sequence[int]], pad_id: int) -> tuple[np.ndarray, np.ndarray]:
    """Right-pad to the longest row. Returns (input_ids, attention_mask) as int64 matrices."""
    width = max(len(r) for r in rows)
    ids = np.full((len(rows), width), pad_id, dtype=np.int64)
    mask = np.zeros((len(rows), width), dtype=np.int64)
    for i, row in enumerate(rows):
        ids[i, : len(row)] = row
        mask[i, : len(row)] = 1
    return ids, mask


def mean_pool(hidden: np.ndarray, mask: np.ndarray) -> np.ndarray:
    weights = mask[..., None].astype(np.float32)
    summed = (hidden.astype(np.float32) * weights).sum(axis=1)
    return summed / np.clip(weights.sum(axis=1), 1e-9, None)


def l2_normalise(mat: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return (mat / norms).astype(np.float32)


class LeanTextEmbedder:
    """Drop-in `TextEmbedder` over an exported lean model directory (needs onnxruntime + sentencepiece)."""

    def __init__(
        self, model_dir: Path, *, expected_model: str | None = None, threads: int = 0, batch_size: int = 32
    ) -> None:
        import onnxruntime as ort
        import sentencepiece as spm

        self.manifest = LeanManifest.load(model_dir)
        if expected_model and self.manifest.model != expected_model:
            raise ValueError(f"{model_dir} holds {self.manifest.model!r}, not the configured {expected_model!r}")
        self.name = self.manifest.model
        self.dim = self.manifest.dim

        opts = ort.SessionOptions()
        if threads > 0:
            opts.intra_op_num_threads = threads
            opts.inter_op_num_threads = 1
        # Allocate per run instead of growing an arena that is never returned: the API serves one short
        # query at a time, and a burst of long documents should not raise the steady-state footprint.
        opts.enable_cpu_mem_arena = False
        self._session = ort.InferenceSession(str(model_dir / ENCODER_FILE), opts, providers=["CPUExecutionProvider"])
        self._inputs = {i.name for i in self._session.get_inputs()}
        if EMBEDS_INPUT not in self._inputs:
            raise ValueError(f"{model_dir / ENCODER_FILE} has no {EMBEDS_INPUT!r} input; re-run export-lean-model")
        self._sp = spm.SentencePieceProcessor(model_file=str(model_dir / SPM_FILE))
        self._table = np.load(model_dir / TABLE_FILE, mmap_mode="r")
        if self._table.ndim != 2 or self._table.shape[1] != self.dim:
            raise ValueError(f"{model_dir / TABLE_FILE} has shape {self._table.shape}, expected [vocab, {self.dim}]")
        self._batch_size = batch_size
        self._lock = threading.Lock()

    def token_ids(self, texts: Sequence[str]) -> list[list[int]]:
        return [to_model_ids(p, self.manifest) for p in self._sp.encode(list(texts))]

    def _run(self, texts: Sequence[str]) -> np.ndarray:
        ids, mask = pad_batch(self.token_ids(texts), self.manifest.pad_id)
        feeds = {"input_ids": ids, "attention_mask": mask, EMBEDS_INPUT: np.ascontiguousarray(self._table[ids])}
        if "token_type_ids" in self._inputs:
            feeds["token_type_ids"] = np.zeros_like(ids)
        hidden = self._session.run(None, feeds)[0]
        return mean_pool(np.asarray(hidden), mask)

    def embed(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        with self._lock:
            parts = [self._run(texts[i : i + self._batch_size]) for i in range(0, len(texts), self._batch_size)]
        return l2_normalise(np.concatenate(parts))

    def embed_query(self, text: str) -> np.ndarray:
        return self.embed([text])[0]
