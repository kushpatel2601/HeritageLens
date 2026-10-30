"""Retrieval primitives used by the SQLite backend: query parsing, BM25, dense top-k, snippets,
and the translation-memory lookup that lets curated/GPU translations survive re-indexing."""

from __future__ import annotations

import numpy as np

from app.services.pipeline.index import build_chunks, lookup_translation, norm
from app.services.search import Bm25, QueryTerms, _top_k, doc_tokens, make_snippet
from app.services.text.entities import build_gazetteer


class TestQueryTerms:
    def test_native_query_gets_phonetic_terms(self) -> None:
        t = QueryTerms.parse("रानी की वाव")
        assert "रानी" in t.raw
        assert {"rani", "vav"} <= set(t.phonetic)

    def test_all_is_deduplicated(self) -> None:
        t = QueryTerms.parse("Patan patan PATAN")
        assert t.all.count("patan") == 1


class TestBm25:
    docs = [
        doc_tokens("Rani ki Vav is a stepwell in Patan", None, "rani ki vav is a stepvel in patan"),
        doc_tokens("Adalaj stepwell near Gandhinagar", None, None),
        doc_tokens("Ajrakh block printing uses natural dyes", None, None),
    ]

    def test_ranks_by_relevance(self) -> None:
        hits = Bm25(self.docs).search(["stepwell", "patan"], k=10)
        assert [i for i, _ in hits] == [0, 1]
        assert hits[0][1] > hits[1][1] > 0

    def test_rare_terms_weigh_more(self) -> None:
        bm = Bm25(self.docs)
        [(_, rare)] = bm.search(["ajrakh"], k=1)
        [(_, common), _] = bm.search(["stepwell"], k=2)
        assert rare > common

    def test_allowed_mask_filters(self) -> None:
        hits = Bm25(self.docs).search(["stepwell"], k=10, allowed=np.array([False, True, True]))
        assert [i for i, _ in hits] == [1]

    def test_unknown_terms_and_empty_corpus(self) -> None:
        assert Bm25(self.docs).search(["zzz"], k=5) == []
        assert Bm25([]).search(["x"], k=5) == []


class TestDenseTopK:
    def test_orders_by_cosine_and_respects_mask(self) -> None:
        m = np.eye(4, dtype=np.float32)
        q = np.array([0.1, 0.9, 0.5, 0.0], dtype=np.float32)
        assert [i for i, _ in _top_k(m, q, 2, None)] == [1, 2]
        masked = _top_k(m, q, 4, np.array([True, False, True, True]))
        assert [i for i, _ in masked] == [2, 0, 3]

    def test_empty_matrix(self) -> None:
        assert _top_k(np.zeros((0, 4), dtype=np.float32), np.ones(4, dtype=np.float32), 3, None) == []


class TestSnippets:
    def test_short_text_highlights_raw_and_phonetic_matches(self) -> None:
        text = "The Raani ki Vaav at Patan"
        snip = make_snippet(text, raw={"patan"}, phon={"rani", "vav"})
        assert [text[s:e] for s, e in snip.highlights] == ["Raani", "Vaav", "Patan"]
        assert not snip.prefix_ellipsis and not snip.suffix_ellipsis

    def test_long_text_is_windowed_around_first_hit(self) -> None:
        text = ("filler words " * 60) + "the Modhera sun temple " + ("more filler " * 60)
        snip = make_snippet(text, raw={"modhera"}, phon=set(), width=120)
        assert snip.prefix_ellipsis and snip.suffix_ellipsis
        assert len(snip.text) <= 120
        [(s, e)] = snip.highlights
        assert snip.text[s:e] == "Modhera"


class TestTranslationMemory:
    memory = {
        norm("पहला अनुच्छेद"): ["First paragraph", "curated"],
        norm("दूसरा   अनुच्छेद"): ["Second paragraph", "curated"],
        norm("कोशिश की गई"): ["", "indictrans2"],
    }

    def test_exact_hit_ignores_whitespace(self) -> None:
        assert lookup_translation("पहला\n अनुच्छेद", self.memory) == ("First paragraph", "curated")

    def test_paragraphs_are_stitched(self) -> None:
        hit = lookup_translation("पहला अनुच्छेद\n\nदूसरा अनुच्छेद", self.memory)
        assert hit == ("First paragraph\n\nSecond paragraph", "curated")

    def test_partial_paragraph_coverage_is_a_miss(self) -> None:
        assert lookup_translation("पहला अनुच्छेद\n\nतीसरा अनुच्छेद", self.memory) is None

    def test_attempted_but_empty_is_still_a_hit(self) -> None:
        assert lookup_translation("कोशिश की गई", self.memory) == ("", "indictrans2")

    def test_build_chunks_marks_hits_and_skips_english(self) -> None:
        gaz = build_gazetteer([])
        drafts = build_chunks(
            [(1, "पहला अनुच्छेद"), (2, "कोशिश की गई"), (3, "नया पाठ"), (4, "English text")],
            self.memory,
            gaz,
            max_chars=700,
            overlap=0,
        )
        got = [(d.page_no, d.language, d.tm_hit, d.translation) for d in drafts]
        assert got == [
            (1, "hi", True, "First paragraph"),
            (2, "hi", True, None),  # attempted: not re-requested, nothing to show
            (3, "hi", False, None),  # unseen: will be sent to the GPU translator
            (4, "en", False, None),
        ]
        assert all(d.phonetic and d.phonetic.isascii() for d in drafts)
