"""Language-code bridges between the archive (ISO 639-1, as detected by the API) and model vocabularies."""

from __future__ import annotations

# FLORES-200 codes - shared by NLLB-200 and AI4Bharat IndicTrans2.
FLORES: dict[str, str] = {
    "en": "eng_Latn",
    "hi": "hin_Deva",
    "gu": "guj_Gujr",
    "mr": "mar_Deva",
    "sa": "san_Deva",
    "pa": "pan_Guru",
    "bn": "ben_Beng",
    "ta": "tam_Taml",
    "te": "tel_Telu",
    "kn": "kan_Knda",
    "ml": "mal_Mlym",
    "or": "ory_Orya",
    "ur": "urd_Arab",
}

# Tesseract 4/5 LSTM traineddata names.
TESSERACT: dict[str, str] = {
    "en": "eng",
    "hi": "hin",
    "gu": "guj",
    "mr": "mar",
    "sa": "san",
    "pa": "pan",
    "bn": "ben",
    "ta": "tam",
    "te": "tel",
    "kn": "kan",
    "ml": "mal",
    "or": "ori",
    "ur": "urd",
}

# Tesseract OSD script names -> candidate language models (most specific first).
OSD_SCRIPT_LANGS: dict[str, tuple[str, ...]] = {
    "Devanagari": ("hin", "mar", "san"),
    "Gujarati": ("guj",),
    "Gurmukhi": ("pan",),
    "Bengali": ("ben",),
    "Tamil": ("tam",),
    "Telugu": ("tel",),
    "Kannada": ("kan",),
    "Malayalam": ("mal",),
    "Oriya": ("ori",),
    "Arabic": ("urd",),
    "Latin": ("eng",),
}

NAMES: dict[str, str] = {
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


def langs_for_script(script: str | None, available: set[str]) -> str | None:
    """Tesseract OSD reported ``script`` -> the most specific installed model (+ English for mixed
    annotations), or ``None`` when we have nothing for that script."""
    for lang in OSD_SCRIPT_LANGS.get(script or "", ()):
        if lang in available:
            return lang if lang == "eng" or "eng" not in available else f"{lang}+eng"
    return None


def tesseract_langs(hint: str | None, available: set[str], default: str = "guj+hin+eng") -> str:
    """Pick a Tesseract language string. A known hint gets its model plus English (archival notes
    often mix scripts); otherwise fall back to ``default`` restricted to installed models."""
    wanted = [TESSERACT[hint], "eng"] if hint in TESSERACT else default.split("+")
    picked = [lang for lang in dict.fromkeys(wanted) if lang in available]
    return "+".join(picked) or ("eng" if "eng" in available else next(iter(sorted(available)), "eng"))
