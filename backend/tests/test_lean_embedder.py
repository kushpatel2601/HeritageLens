"""The lean text-embedding runtime: id mapping, batching and pooling, backend selection, and the ONNX
graph surgery behind `app.cli export-lean-model`. ONNX Runtime and SentencePiece are faked so the
logic is tested without the `ml` extra; the surgery test runs when `onnx` is installed."""

from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from app.services import embeddings
from app.services import lean_embedder as lean
from app.services.lean_embedder import LeanManifest, LeanTextEmbedder, mean_pool, pad_batch, to_model_ids
from app.services.lean_export import ExportError, derive_manifest, strip_word_embeddings

MODEL = "test/xlmr-mini"
MANIFEST = LeanManifest(model=MODEL, dim=4, max_length=6, bos_id=0, eos_id=2, pad_id=1, unk_id=3, id_offset=1)


def test_to_model_ids_maps_offsets_unknowns_and_truncates() -> None:
    assert to_model_ids([], MANIFEST) == [0, 2]
    assert to_model_ids([5, 0, 7], MANIFEST) == [0, 6, 3, 8, 2]  # SentencePiece <unk> (0) -> model <unk>
    assert to_model_ids([9, 9, 9, 9, 9, 9, 9], MANIFEST) == [0, 10, 10, 10, 10, 2]  # head kept, max_length total


def test_pad_batch_and_mean_pool_ignore_padding() -> None:
    ids, mask = pad_batch([[0, 5, 2], [0, 2]], pad_id=1)
    assert ids.tolist() == [[0, 5, 2], [0, 2, 1]]
    assert mask.tolist() == [[1, 1, 1], [1, 1, 0]]
    hidden = np.ones((2, 3, 4), dtype=np.float16)
    hidden[1, 2] = 1e4  # a padded position must not leak into the mean
    pooled = mean_pool(hidden, mask)
    assert pooled.dtype == np.float32 and np.allclose(pooled, 1.0)


def test_manifest_round_trip_and_format_guard(tmp_path: Path) -> None:
    MANIFEST.save(tmp_path)
    assert LeanManifest.load(tmp_path) == MANIFEST
    (tmp_path / lean.MANIFEST_FILE).write_text('{"format": 99}', encoding="utf-8")
    with pytest.raises(ValueError, match="unsupported lean model format"):
        LeanManifest.load(tmp_path)


# ------------------------------------------------------------------ runtime over fake ORT / SentencePiece
class _FakeSession:
    """An identity 'transformer': the hidden state is the looked-up word vectors."""

    calls: list[dict[str, np.ndarray]]

    def __init__(self, path: str, opts: Any, providers: list[str]) -> None:
        self.opts = opts
        self.inputs = ["input_ids", "attention_mask", "token_type_ids", lean.EMBEDS_INPUT]
        _FakeSession.calls = []

    def get_inputs(self) -> list[Any]:
        return [types.SimpleNamespace(name=n) for n in self.inputs]

    def run(self, _outputs: None, feeds: dict[str, np.ndarray]) -> list[np.ndarray]:
        _FakeSession.calls.append(feeds)
        return [feeds[lean.EMBEDS_INPUT].astype(np.float32)]


class _FakeSentencePiece:
    """Each word becomes one piece whose id is its length (0 for words longer than 6: SentencePiece <unk>)."""

    def __init__(self, model_file: str) -> None:
        self.model_file = model_file

    def encode(self, texts: list[str]) -> list[list[int]]:
        return [[len(w) if len(w) <= 6 else 0 for w in t.split()] for t in texts]


@pytest.fixture
def lean_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    ort = types.ModuleType("onnxruntime")
    ort.SessionOptions = types.SimpleNamespace  # type: ignore[attr-defined]
    ort.InferenceSession = _FakeSession  # type: ignore[attr-defined]
    spm = types.ModuleType("sentencepiece")
    spm.SentencePieceProcessor = _FakeSentencePiece  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "onnxruntime", ort)
    monkeypatch.setitem(sys.modules, "sentencepiece", spm)

    table = np.random.default_rng(7).normal(size=(12, MANIFEST.dim)).astype(np.float16)
    np.save(tmp_path / lean.TABLE_FILE, table)
    (tmp_path / lean.ENCODER_FILE).write_bytes(b"fake")
    (tmp_path / lean.SPM_FILE).write_bytes(b"fake")
    MANIFEST.save(tmp_path)
    return tmp_path


def _expected(table: np.ndarray, ids: list[int]) -> np.ndarray:
    v = table[ids].astype(np.float32).mean(axis=0)
    return v / np.linalg.norm(v)


def test_lean_embedder_batches_pools_and_normalises(lean_dir: Path) -> None:
    assert lean.is_lean_model_dir(lean_dir)
    emb = LeanTextEmbedder(lean_dir, expected_model=MODEL, threads=1, batch_size=2)
    assert (emb.name, emb.dim) == (MODEL, 4)
    texts = ["ab cde", "x", "toolongword ab"]
    vecs = emb.embed(texts)

    table = np.load(lean_dir / lean.TABLE_FILE)
    assert vecs.shape == (3, 4) and vecs.dtype == np.float32
    assert np.allclose(vecs[0], _expected(table, [0, 3, 4, 2]), atol=1e-3)
    assert np.allclose(vecs[2], _expected(table, [0, 3, 3, 2]), atol=1e-3)  # long word -> <unk> (3)
    assert len(_FakeSession.calls) == 2  # batch_size=2 -> two runs
    first = _FakeSession.calls[0]
    assert first["input_ids"].tolist() == [[0, 3, 4, 2], [0, 2, 2, 1]]
    assert not first["token_type_ids"].any() and first[lean.EMBEDS_INPUT].dtype == np.float16
    assert np.allclose(emb.embed_query("ab cde"), vecs[0])
    assert emb.embed([]).shape == (0, 4)


def test_lean_embedder_refuses_a_different_model_or_graph(lean_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValueError, match="not the configured"):
        LeanTextEmbedder(lean_dir, expected_model="another/model")
    monkeypatch.setattr(_FakeSession, "get_inputs", lambda self: [types.SimpleNamespace(name="input_ids")])
    with pytest.raises(ValueError, match="inputs_embeds"):
        LeanTextEmbedder(lean_dir)


# ------------------------------------------------------------------ backend selection
class _Recorder:
    def __init__(self, name: str, fail: bool = False) -> None:
        self.name, self.fail, self.calls = name, fail, []

    def __call__(self, *args: Any, **kwargs: Any) -> types.SimpleNamespace:
        self.calls.append((args, kwargs))
        if self.fail:
            raise RuntimeError(f"{self.name} broken")
        return types.SimpleNamespace(name=self.name, dim=384)


@pytest.mark.parametrize(
    ("embedder", "has_dir", "lean_fails", "expected"),
    [
        ("auto", True, False, "lean"),
        ("auto", True, True, "fastembed"),
        ("auto", False, False, "fastembed"),
        ("lean", False, False, "lean"),
        ("hashing", True, False, "hashing-ngram-384"),
    ],
)
def test_backend_selection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, embedder: str, has_dir: bool, lean_fails: bool, expected: str
) -> None:
    from tests.conftest import make_settings

    fake_lean, fake_fast = _Recorder("lean", fail=lean_fails), _Recorder("fastembed")
    monkeypatch.setattr(lean, "LeanTextEmbedder", fake_lean)
    monkeypatch.setattr(lean, "is_lean_model_dir", lambda _p: has_dir)
    monkeypatch.setattr(embeddings, "FastEmbedTextEmbedder", fake_fast)
    settings = make_settings(tmp_path, embedder=embedder, embed_threads=1)

    assert embeddings._build_text_embedder(settings).name == expected
    if expected == "lean":
        assert fake_lean.calls[0][1] == {"expected_model": settings.text_embed_model, "threads": 1}


def test_explicit_lean_backend_does_not_fall_back(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.conftest import make_settings

    monkeypatch.setattr(lean, "LeanTextEmbedder", _Recorder("lean", fail=True))
    with pytest.raises(RuntimeError, match="lean broken"):
        embeddings._build_text_embedder(make_settings(tmp_path, embedder="lean"))


# ------------------------------------------------------------------ export helpers
class _FakeReference:
    def __init__(self, offset: int) -> None:
        self.offset = offset
        self.truncation = {"max_length": 128}
        self.padding = {"pad_id": 1}

    def encode(self, text: str) -> types.SimpleNamespace:
        return types.SimpleNamespace(ids=[0, 2])

    def token_to_id(self, piece: str) -> int | None:
        return 3 if piece == "<unk>" else int(piece[1:]) + self.offset


class _FakeVocab:
    def unk_id(self) -> int:
        return 0

    def get_piece_size(self) -> int:
        return 5000

    def id_to_piece(self, i: int) -> str:
        return "<unk>" if i == 0 else f"p{i}"


def test_derive_manifest_reads_ids_and_offset() -> None:
    m = derive_manifest(MODEL, 384, _FakeReference(offset=1), _FakeVocab())
    assert (m.max_length, m.bos_id, m.eos_id, m.pad_id, m.unk_id, m.id_offset) == (128, 0, 2, 1, 3, 1)


def test_derive_manifest_rejects_misaligned_vocabularies() -> None:
    ref = _FakeReference(offset=1)
    ref.token_to_id = lambda piece: 3 if piece == "<unk>" else int(piece[1:]) % 7  # type: ignore[method-assign]
    with pytest.raises(ExportError, match="do not line up"):
        derive_manifest(MODEL, 384, ref, _FakeVocab())


def _tiny_bert(shared_table: bool = False) -> Any:
    """input_ids -> Gather(word table) + Gather(position table) -> Cast(float) -> last_hidden_state."""
    onnx = pytest.importorskip("onnx")
    from onnx import TensorProto, helper, numpy_helper

    rng = np.random.default_rng(3)
    word = numpy_helper.from_array(rng.normal(size=(10, 4)).astype(np.float16), "embeddings.word_embeddings.weight")
    pos = numpy_helper.from_array(rng.normal(size=(10, 4)).astype(np.float16), "embeddings.position.weight")
    nodes = [
        helper.make_node("Gather", ["embeddings.word_embeddings.weight", "input_ids"], ["word"]),
        helper.make_node(
            "Gather", ["embeddings.word_embeddings.weight" if shared_table else pos.name, "input_ids"], ["p"]
        ),
        helper.make_node("Add", ["word", "p"], ["sum"]),
        helper.make_node("Cast", ["sum"], ["last_hidden_state"], to=TensorProto.FLOAT),
    ]
    graph = helper.make_graph(
        nodes,
        "tiny",
        [helper.make_tensor_value_info("input_ids", TensorProto.INT64, ["b", "s"])],
        [helper.make_tensor_value_info("last_hidden_state", TensorProto.FLOAT, ["b", "s", 4])],
        [word, pos],
    )
    return onnx.helper.make_model(graph, opset_imports=[helper.make_opsetid("", 13)], ir_version=8)


def test_strip_word_embeddings_preserves_the_computation() -> None:
    from onnx import numpy_helper

    original = _tiny_bert()
    stripped = _tiny_bert()
    expected_table = numpy_helper.to_array(stripped.graph.initializer[0])
    table = strip_word_embeddings(stripped)

    assert np.array_equal(table, expected_table)
    assert [i.name for i in stripped.graph.input] == ["input_ids", lean.EMBEDS_INPUT]
    assert "embeddings.word_embeddings.weight" not in {t.name for t in stripped.graph.initializer}

    ort = pytest.importorskip("onnxruntime")
    ids = np.array([[0, 5, 9, 2]], dtype=np.int64)
    before = ort.InferenceSession(original.SerializeToString()).run(None, {"input_ids": ids})[0]
    after = ort.InferenceSession(stripped.SerializeToString()).run(
        None, {"input_ids": ids, lean.EMBEDS_INPUT: table[ids]}
    )[0]
    assert np.array_equal(before, after)


def test_strip_word_embeddings_refuses_tied_weights() -> None:
    with pytest.raises(ExportError, match="shared"):
        strip_word_embeddings(_tiny_bert(shared_table=True))
