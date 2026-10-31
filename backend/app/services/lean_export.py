"""Export the lean MiniLM runtime (`app.services.lean_embedder`) from the model fastembed serves.

Runs once, at image build time, and needs the `ml` and `export` extras (fastembed, sentencepiece, onnx).
Nothing is published unless the new runtime reproduces the reference tokenizer's ids *and* fastembed's
vectors on a multilingual probe set plus any archive texts passed in, so the stored index stays valid.
"""

from __future__ import annotations

import gc
import shutil
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from app.services.lean_embedder import (
    EMBEDS_INPUT,
    ENCODER_FILE,
    SPM_FILE,
    TABLE_FILE,
    LeanManifest,
    LeanTextEmbedder,
    l2_normalise,
)

# Scripts, joiners, width variants, whitespace and an over-long text that exercises truncation.
PROBE_TEXTS: tuple[str, ...] = (
    "stepwell water architecture",
    "Rani ki Vav (रानी की वाव), Patan — UNESCO World Heritage Site since 2014!",
    "રાણકી વાવ, પાટણ",
    "सूर्य मंदिर मोढेरा",
    "क्‍ष ज्ञ श्र",
    "می‌خواهم قلعہ دیکھنا",
    "தஞ்சாவூர் பெரிய கோயில்",
    "বিষ্ণুপুর টেরাকোটা মন্দির",
    "万里长城",
    "Ｆｕｌｌ－ｗｉｄｔｈ １２３, café naïve",
    "emoji 🏛️🕌 temple",
    "  leading,\ttabs\nand   newlines  ",
    "",
    "1,234.56 AD/CE c. 1063",
    "carved stepwell galleries " * 120,
)
MIN_COSINE = 0.9999


class ExportError(RuntimeError):
    pass


@dataclass(frozen=True)
class ExportReport:
    out_dir: Path
    manifest: LeanManifest
    files_mb: dict[str, float]
    texts_checked: int
    min_cosine: float


def strip_word_embeddings(proto: Any) -> np.ndarray:
    """Cut `Gather(word_table, input_ids)` out of an ONNX graph, in place, and return the table.

    The gathered tensor becomes a new graph input (`inputs_embeds`) the runtime fills from a memory-mapped
    copy of the table. `input_ids` stays an input because shape nodes still read it.
    """
    from onnx import helper, numpy_helper

    graph = proto.graph
    inits = {t.name: t for t in graph.initializer}
    candidates = [n for n in graph.node if n.op_type == "Gather" and n.input[1] == "input_ids" and n.input[0] in inits]
    if len({n.input[0] for n in candidates}) > 1:
        candidates = [n for n in candidates if "word_embeddings" in n.input[0]]
    if len({n.input[0] for n in candidates}) != 1:
        raise ExportError("no unique Gather(<word table>, input_ids) node: not a BERT / XLM-R style graph")
    node = candidates[0]
    table_name, gathered = node.input[0], node.output[0]
    if any(table_name in n.input for n in graph.node if n is not node):
        raise ExportError(f"{table_name} is shared with other nodes (tied weights); cannot move it out")
    if any(o.name == gathered for o in graph.output):
        raise ExportError(f"{gathered} is a graph output; cannot replace it with an input")

    table = numpy_helper.to_array(inits[table_name])
    graph.node.remove(node)
    graph.initializer.remove(inits[table_name])
    for n in graph.node:
        for i, name in enumerate(n.input):
            if name == gathered:
                n.input[i] = EMBEDS_INPUT
    elem_type = helper.np_dtype_to_tensor_dtype(table.dtype)
    graph.input.append(
        helper.make_tensor_value_info(EMBEDS_INPUT, elem_type, ["batch_size", "sequence_length", table.shape[1]])
    )
    return table


def derive_manifest(model: str, dim: int, reference: Any, sp: Any) -> LeanManifest:
    """Read the special ids, limits and SentencePiece id offset off the reference tokenizer."""
    truncation, padding = reference.truncation or {}, reference.padding or {}
    if not truncation.get("max_length") or padding.get("pad_id") is None:
        raise ExportError("the reference tokenizer has no truncation / padding configured")
    specials = reference.encode("").ids
    if len(specials) != 2:
        raise ExportError(f"expected text to be wrapped in two special tokens, got {specials}")
    unk_id = reference.token_to_id(sp.id_to_piece(sp.unk_id()))
    offsets: set[int | None] = set()
    for piece_id in range(3, sp.get_piece_size(), 997):
        model_id = reference.token_to_id(sp.id_to_piece(piece_id))
        offsets.add(None if model_id is None else model_id - piece_id)
    offset = next(iter(offsets)) if len(offsets) == 1 else None
    if unk_id is None or offset is None:
        raise ExportError(f"SentencePiece and tokenizer vocabularies do not line up (offsets {offsets})")
    return LeanManifest(
        model=model,
        dim=dim,
        max_length=int(truncation["max_length"]),
        bos_id=specials[0],
        eos_id=specials[1],
        pad_id=int(padding["pad_id"]),
        unk_id=unk_id,
        id_offset=offset,
    )


def _model_description(model: str) -> dict[str, Any]:
    from fastembed import TextEmbedding

    for desc in TextEmbedding.list_supported_models():
        if desc["model"] == model:
            return dict(desc)
    raise ExportError(f"fastembed does not serve {model!r}")


def export_lean_model(model: str, out_dir: Path, *, cache_dir: Path, extra_texts: Sequence[str] = ()) -> ExportReport:
    import onnx
    import sentencepiece as spm
    from fastembed import TextEmbedding
    from fastembed.common.preprocessor_utils import load_tokenizer
    from huggingface_hub import hf_hub_download, snapshot_download

    desc = _model_description(model)
    repo = (desc.get("sources") or {}).get("hf")
    if not repo:
        raise ExportError(f"{model!r} has no Hugging Face source in fastembed")
    src = Path(snapshot_download(repo, cache_dir=str(cache_dir), allow_patterns=[desc["model_file"], "*.json"]))
    # The ONNX repack drops the SentencePiece model; the upstream sentence-transformers repo still ships it.
    spm_path = Path(hf_hub_download(model, SPM_FILE, cache_dir=str(cache_dir)))

    reference, _ = load_tokenizer(src)
    sp = spm.SentencePieceProcessor(model_file=str(spm_path))
    manifest = derive_manifest(model, int(desc["dim"]), reference, sp)

    work = out_dir.with_name(out_dir.name + ".partial")
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    proto = onnx.load(str(src / desc["model_file"]))
    table = strip_word_embeddings(proto)
    if table.shape[1] != manifest.dim:
        raise ExportError(f"word table is {table.shape}, expected [vocab, {manifest.dim}]")
    np.save(work / TABLE_FILE, table)
    onnx.save(proto, str(work / ENCODER_FILE))
    del proto, table
    gc.collect()
    shutil.copyfile(spm_path, work / SPM_FILE)
    manifest.save(work)

    texts = [*PROBE_TEXTS, *extra_texts]
    lean = LeanTextEmbedder(work, expected_model=model)
    mismatched = [t for t, ids in zip(texts, lean.token_ids(texts), strict=True) if reference.encode(t).ids != ids]
    if mismatched:
        raise ExportError(f"{len(mismatched)}/{len(texts)} texts tokenise differently, e.g. {mismatched[0][:60]!r}")
    got = lean.embed(texts)
    del lean
    gc.collect()
    ref = l2_normalise(np.asarray(list(TextEmbedding(model, cache_dir=str(cache_dir)).embed(texts)), dtype=np.float32))
    min_cosine = float((got * ref).sum(axis=1).min())
    if min_cosine < MIN_COSINE:
        raise ExportError(f"lean vectors drift from fastembed (min cosine {min_cosine:.6f} < {MIN_COSINE})")

    shutil.rmtree(out_dir, ignore_errors=True)
    work.replace(out_dir)
    files_mb = {f.name: round(f.stat().st_size / 2**20, 1) for f in sorted(out_dir.iterdir())}
    return ExportReport(out_dir, manifest, files_mb, len(texts), round(min_cosine, 6))
