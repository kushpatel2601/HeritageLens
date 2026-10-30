from __future__ import annotations

import pytest

from heritage_gpu.textproc import (
    assemble_tesseract,
    clean_caption,
    normalize,
    split_sentences,
    translate_documents,
)


def test_normalize_composes_and_tidies_whitespace() -> None:
    assert normalize("Cafe\u0301\r\n\r\n\r\n\r\n  rani\u00a0 ki\tvav  ") == "Caf\u00e9\n\nrani ki vav"


def test_split_sentences_on_latin_and_indic_terminators() -> None:
    text = "पहला वाक्य। दूसरा वाक्य॥ Third one! ચોથું વાક્ય.\nFifth"
    assert split_sentences(text) == ["पहला वाक्य।", "दूसरा वाक्य॥", "Third one!", "ચોથું વાક્ય.", "Fifth"]
    assert split_sentences("  \n\n ") == []


def test_split_sentences_never_exceeds_the_budget_and_loses_nothing() -> None:
    long = ", ".join(f"clause number {i} about the carved panels of the stepwell" for i in range(30))
    units = split_sentences(long, max_chars=120)
    assert len(units) > 1
    assert all(len(u) <= 120 for u in units)
    assert " ".join(units).split() == long.split()
    giant_word = "x" * 300  # a single unbreakable token is kept whole rather than dropped
    assert split_sentences(giant_word, max_chars=50) == [giant_word]


def test_translate_documents_batches_by_length_and_restores_order() -> None:
    calls: list[list[str]] = []

    def fake(batch: list[str]) -> list[str]:
        calls.append(batch)
        return [s.upper() for s in batch]

    texts = ["a. bb. ccc.", "", "dddd.", "e."]
    out = translate_documents(texts, fake, batch_size=2)
    assert out == ["A. BB. CCC.", "", "DDDD.", "E."]
    assert [len(c) for c in calls] == [2, 2, 1]
    assert calls[0] == ["dddd.", "ccc."]  # longest first keeps padding low


def test_translate_documents_detects_misbehaving_translators() -> None:
    with pytest.raises(RuntimeError, match="2 inputs"):
        translate_documents(["one. two."], lambda batch: batch[:1])


def test_assemble_tesseract_rebuilds_paragraphs_and_mean_confidence() -> None:
    data = {
        "text": ["", "Rani", "ki", "Vav", " ", "Patan", "1063"],
        "block_num": [0, 1, 1, 1, 1, 2, 2],
        "par_num": [0, 1, 1, 1, 1, 1, 1],
        "line_num": [0, 1, 1, 2, 2, 1, 1],
        "conf": ["-1", "90", "80", "70", "-1", "x", 60],
    }
    text, conf = assemble_tesseract(data)
    assert text == "Rani ki\nVav\n\nPatan 1063"
    assert conf == pytest.approx(0.75)
    assert assemble_tesseract({"text": []}) == ("", None)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("arafed man standing in front of a stepwell", "Man standing in front of a stepwell"),
        ("a photograph of a carved stone pillar .", "A carved stone pillar"),
        ("araffe", ""),
        ("there is a temple", "There is a temple"),
    ],
)
def test_clean_caption(raw: str, expected: str) -> None:
    assert clean_caption(raw, prompt="a photograph of") == expected
