"""Cross-script phonetic keys.

Lets "Rani ki Vav", "रानी की वाव" and "રાણી કી વાવ" all collapse to the same key, so researchers can
search the archive in whichever script they type. Native scripts are transliterated to ITRANS, then
both Latin and transliterated text go through the same normalisation (aspiration folding, vowel
length folding, schwa deletion, doubled-letter collapsing).
"""

from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

from indic_transliteration import sanscript
from indic_transliteration.sanscript import transliterate

from app.services.text.scripts import char_script

_SCHEMES = {
    "Deva": sanscript.DEVANAGARI,
    "Gujr": sanscript.GUJARATI,
    "Guru": sanscript.GURMUKHI,
    "Beng": sanscript.BENGALI,
    "Taml": sanscript.TAMIL,
    "Telu": sanscript.TELUGU,
    "Knda": sanscript.KANNADA,
    "Mlym": sanscript.MALAYALAM,
    "Orya": sanscript.ORIYA,
}

# Order matters: longest patterns first.
_FOLDS: list[tuple[str, str]] = [
    ("chh", "c"),
    ("ch", "c"),
    ("sh", "s"),
    ("kh", "k"),
    ("gh", "g"),
    ("th", "t"),
    ("dh", "d"),
    ("ph", "p"),
    ("bh", "b"),
    ("jh", "j"),
    ("ee", "i"),
    ("oo", "u"),
    ("w", "v"),
    ("z", "j"),
    ("q", "k"),
    ("x", "ks"),
]
_ITRANS_MARKS = re.compile(r"[.~^`'_]")
_NON_WORD = re.compile(r"[^a-z0-9 ]+")
_DUPES = re.compile(r"([a-z])\1+")
_WS = re.compile(r"\s+")


def _to_latin(text: str) -> str:
    """Transliterate runs of native-script characters to ITRANS; leave Latin untouched."""
    out: list[str] = []
    run: list[str] = []
    run_script: str | None = None

    def flush() -> None:
        nonlocal run, run_script
        if run:
            seg = "".join(run)
            scheme = _SCHEMES.get(run_script or "")
            latin = transliterate(seg, scheme, sanscript.ITRANS) if scheme else seg
            out.append(_ITRANS_MARKS.sub("", latin))  # nukta/chandrabindu markers must not split words
            run, run_script = [], None

    for ch in text:
        sc = char_script(ch)
        if sc in _SCHEMES:
            if run_script not in (None, sc):
                flush()
            run.append(ch)
            run_script = sc
        else:
            flush()
            out.append(ch)
    flush()
    return "".join(out)


@lru_cache(maxsize=50_000)
def phonetic_word(word: str) -> str:
    w = word
    for a, b in _FOLDS:
        w = w.replace(a, b)
    w = _DUPES.sub(r"\1", w)
    if len(w) > 3 and w.endswith("a"):
        w = w[:-1]  # schwa deletion: "vava" -> "vav", "patana" -> "patan"
    return w


def phonetic_key(text: str) -> str:
    latin = _to_latin(text)
    latin = unicodedata.normalize("NFKD", latin)
    latin = "".join(ch for ch in latin if not unicodedata.combining(ch)).lower()
    latin = _NON_WORD.sub(" ", latin)
    words = [phonetic_word(w) for w in _WS.split(latin) if w]
    return " ".join(w for w in words if w)


def transliterate_to_latin(text: str) -> str:
    """Human-readable IAST romanisation, used for display ("Rāṇī kī Vāva")."""
    out: list[str] = []
    for token in re.split(r"(\s+)", text):
        sc = next((s for ch in token if (s := char_script(ch)) in _SCHEMES), None)
        out.append(transliterate(token, _SCHEMES[sc], sanscript.IAST) if sc else token)
    return "".join(out)
