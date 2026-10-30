"""Unicode-script aware language detection for Indic archives (no ML dependency)."""

from __future__ import annotations

import re
from collections import Counter

# `\w` alone splits Indic words at combining vowel signs (category Mn/Mc), so include the blocks.
WORD_RE = re.compile(r"[\w\u0900-\u097F\u0980-\u0DFF]+", re.UNICODE)

# (start, end, script code, default language)
_RANGES: list[tuple[int, int, str, str]] = [
    (0x0900, 0x097F, "Deva", "hi"),
    (0x0A80, 0x0AFF, "Gujr", "gu"),
    (0x0A00, 0x0A7F, "Guru", "pa"),
    (0x0980, 0x09FF, "Beng", "bn"),
    (0x0B80, 0x0BFF, "Taml", "ta"),
    (0x0C00, 0x0C7F, "Telu", "te"),
    (0x0C80, 0x0CFF, "Knda", "kn"),
    (0x0D00, 0x0D7F, "Mlym", "ml"),
    (0x0B00, 0x0B7F, "Orya", "or"),
    (0x0600, 0x06FF, "Arab", "ur"),
]

# Marathi / Sanskrit share Devanagari: a few high-signal function words disambiguate.
_MARATHI_HINTS = {"आहे", "आणि", "होते", "मध्ये", "च्या", "हे", "त्या"}
_SANSKRIT_HINTS = {"अस्ति", "च", "इति", "तत्", "सः", "भवति", "नमः"}

LANGUAGE_NAMES = {
    "en": "English",
    "hi": "Hindi",
    "gu": "Gujarati",
    "mr": "Marathi",
    "sa": "Sanskrit",
    "pa": "Punjabi",
    "bn": "Bengali",
    "ta": "Tamil",
    "te": "Telugu",
    "kn": "Kannada",
    "ml": "Malayalam",
    "or": "Odia",
    "ur": "Urdu",
}


def char_script(ch: str) -> str | None:
    cp = ord(ch)
    for start, end, script, _ in _RANGES:
        if start <= cp <= end:
            return script
    if ch.isascii() and ch.isalpha():
        return "Latn"
    if "\u00c0" <= ch <= "\u024f":
        return "Latn"
    return None


def detect_script(text: str) -> str | None:
    counts = Counter(s for ch in text if (s := char_script(ch)))
    if not counts:
        return None
    return counts.most_common(1)[0][0]


def detect_language(text: str) -> tuple[str | None, str | None]:
    """Return (iso-639-1 language, ISO-15924 script)."""
    script = detect_script(text)
    if script is None:
        return None, None
    if script == "Latn":
        return "en", script
    lang = next(lang for _, _, s, lang in _RANGES if s == script)
    if script == "Deva":
        words = set(text.split())
        if len(words & _MARATHI_HINTS) >= 2:
            lang = "mr"
        elif len(words & _SANSKRIT_HINTS) >= 2:
            lang = "sa"
    return lang, script


def is_indic(script: str | None) -> bool:
    return script not in (None, "Latn")
