"""Multilingual text processing: scripts, cross-script phonetics, historical dates, chunking, entities."""

from __future__ import annotations

import pytest

from app.services.text.chunking import chunk_text
from app.services.text.dates import extract_dates, format_year, normalise_digits
from app.services.text.entities import Gazetteer, build_gazetteer, extract_entities
from app.services.text.phonetic import phonetic_key, transliterate_to_latin
from app.services.text.scripts import detect_language, detect_script, is_indic


class TestScripts:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("Rani ki Vav, Patan", ("en", "Latn")),
            ("रानी की वाव पाटन में है", ("hi", "Deva")),
            ("રાણી કી વાવ પાટણમાં આવેલી છે", ("gu", "Gujr")),
            ("1063 — 1499", (None, None)),
        ],
    )
    def test_detect_language(self, text: str, expected: tuple[str | None, str | None]) -> None:
        assert detect_language(text) == expected

    def test_majority_script_wins_in_mixed_text(self) -> None:
        assert detect_script("Adalaj अडालज की बावड़ी सीढ़ीदार") == "Deva"

    def test_is_indic(self) -> None:
        assert is_indic("Gujr") and is_indic("Deva")
        assert not is_indic("Latn") and not is_indic(None)


class TestPhonetic:
    @pytest.mark.parametrize("variant", ["Rani ki Vav", "Raani-ki-vaav", "रानी की वाव", "રાણી કી વાવ", "RANI KI VAAV"])
    def test_cross_script_variants_share_one_key(self, variant: str) -> None:
        assert phonetic_key(variant) == "rani ki vav"

    @pytest.mark.parametrize(
        ("a", "b"), [("Modhera", "मोढेरा"), ("Chand Baori", "चाँद बावड़ी"), ("Dholavira", "ધોળાવીરા")]
    )
    def test_place_names_match_across_scripts(self, a: str, b: str) -> None:
        assert phonetic_key(a).split()[0] == phonetic_key(b).split()[0]

    def test_iast_romanisation_for_display(self) -> None:
        assert transliterate_to_latin("रानी की वाव") == "rānī kī vāva"

    def test_latin_is_left_readable(self) -> None:
        assert transliterate_to_latin("Patan 1063") == "Patan 1063"


class TestDates:
    def test_vikram_samvat_in_devanagari_digits(self) -> None:
        [d] = extract_dates("संवत ११२० में निर्माण हुआ")
        assert (d.year, d.calendar) == (1063, "vikram-samvat")

    def test_vikram_samvat_in_gujarati(self) -> None:
        [d] = extract_dates("સંવત ૧૫૫૫")
        assert d.year == 1498

    @pytest.mark.parametrize(
        ("text", "year", "calendar"),
        [
            ("completed in 1499 by Rani Rudabai", 1499, "gregorian"),
            ("Harappan city, 2650 BCE", -2650, "gregorian"),
            ("built around AD 1032", 1032, "gregorian"),
            ("an 11th century stepwell", 1050, "century"),
            ("११वीं शताब्दी का कुंड", 1050, "century"),
        ],
    )
    def test_calendars(self, text: str, year: int, calendar: str) -> None:
        [d] = extract_dates(text)
        assert (d.year, d.calendar) == (year, calendar)
        assert text[d.start : d.end] == d.surface

    def test_mentions_are_ordered_and_do_not_overlap(self) -> None:
        years = [d.year for d in extract_dates("Samvat 1555, i.e. 1498 CE; restored in 1890")]
        assert years == [1498, 1498, 1890]

    def test_plain_numbers_are_not_dates(self) -> None:
        assert extract_dates("The well has 7 storeys and 1500 pillars") == []

    def test_helpers(self) -> None:
        assert normalise_digits("૧૫૫૫ / १०६३") == "1555 / 1063"
        assert format_year(-2650) == "2650 BCE"
        assert format_year(1063) == "1063 CE"


class TestChunking:
    def test_short_text_is_one_chunk(self) -> None:
        [c] = chunk_text("A single paragraph.")
        assert (c.seq, c.start, c.overlap, c.body) == (0, 0, 0, "A single paragraph.")

    def test_empty(self) -> None:
        assert chunk_text("  \n\n ") == []

    def test_long_text_overlaps_and_body_strips_context(self) -> None:
        paras = [f"Paragraph {i} describes the stepwell and its carvings in some detail." for i in range(12)]
        text = "\n\n".join(paras)
        chunks = chunk_text(text, max_chars=200, overlap=40)
        assert len(chunks) > 3
        assert [c.seq for c in chunks] == list(range(len(chunks)))
        assert all(len(c.text) <= 200 + 40 for c in chunks)
        for c in chunks[1:]:
            assert c.overlap > 0
            assert text[c.start :].startswith(c.body[:30])
        # every paragraph survives in some chunk body
        bodies = " ".join(c.body for c in chunks)
        assert all(p in bodies for p in paras)

    def test_devanagari_sentences_split_on_danda(self) -> None:
        sentence = "यह बावड़ी ग्यारहवीं शताब्दी में बनाई गई थी। "
        chunks = chunk_text(sentence * 30, max_chars=150, overlap=0)
        assert len(chunks) > 1
        assert all(c.text.endswith("।") for c in chunks[:-1])

    def test_run_on_text_is_hard_wrapped(self) -> None:
        chunks = chunk_text("word " * 400, max_chars=100, overlap=0)
        assert all(len(c.text) <= 100 for c in chunks)


class TestEntities:
    @pytest.fixture
    def gazetteer(self) -> Gazetteer:
        return build_gazetteer(
            [
                (1, "Rani ki Vav", ["Rani ki Vav", "रानी की वाव", "Queen's Stepwell"], 23.8589, 72.1016),
                (2, "Adalaj Stepwell", ["Adalaj Stepwell", "Adalaj", "Rudabai Stepwell"], 23.1667, 72.5806),
            ]
        )

    def test_sites_found_in_any_script(self, gazetteer: Gazetteer) -> None:
        found = gazetteer.find("We visited रानी की वाव and then Raani ki Vaav again")
        assert [(m.kind, m.site_id) for m in found] == [("site", 1), ("site", 1)]
        assert found[0].surface == "रानी की वाव"

    def test_longest_match_wins(self, gazetteer: Gazetteer) -> None:
        [m] = gazetteer.find("the Adalaj Stepwell at dawn")
        assert (m.site_id, m.surface) == (2, "Adalaj Stepwell")

    def test_short_ambiguous_aliases_are_ignored(self) -> None:
        gaz = build_gazetteer([(9, "Vav", ["Vav"], 0.0, 0.0)])
        assert gaz.find("a vav near the village") == []

    def test_entities_merge_places_and_dates(self, gazetteer: Gazetteer) -> None:
        kinds = [(m.kind, m.year) for m in extract_entities("Adalaj was completed in 1499.", gazetteer)]
        assert kinds == [("site", None), ("date", 1499)]
