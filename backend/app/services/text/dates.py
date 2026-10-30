"""Historical date extraction across calendars and scripts.

Handles Gregorian years (CE/AD/BCE), centuries ("11th century", "११वीं शताब्दी"), and the
Vikram Samvat calendar common in Gujarati/Rajasthani inscriptions (VS - 57 = CE).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_DIGITS = str.maketrans("०१२३४५६७८९૦૧૨૩૪૫૬૭૮૯", "01234567890123456789")


@dataclass(frozen=True, slots=True)
class DateMention:
    surface: str
    year: int  # negative = BCE
    calendar: str  # gregorian | vikram-samvat | century
    start: int
    end: int


def normalise_digits(text: str) -> str:
    return text.translate(_DIGITS)


_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # Vikram Samvat: "Vikram Samvat 1555", "V.S. 1555", "संवत १५५५", "સંવત ૧૫૫૫"
    (
        re.compile(
            r"(?:vikram(?:a)?\s+samvat|v\.\s?s\.|samvat|विक्रम\s+संवत|संवत|સંવત|વિક્રમ\s+સંવત)\s*(\d{3,4})",
            re.I,
        ),
        "vs",
    ),
    (re.compile(r"\b(\d{1,4})\s*(?:BCE|B\.C\.E\.|BC|B\.C\.)", re.I), "bce"),
    (re.compile(r"(?:\b(?:AD|A\.D\.)\s*(\d{3,4})\b|\b(\d{3,4})\s*(?:CE|C\.E\.|AD|A\.D\.)(?![a-z]))", re.I), "ce"),
    (re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)[\s-]+century(\s+(?:BCE|BC))?", re.I), "century"),
    (re.compile(r"(\d{1,2})\s*(?:वीं|वी|वें)\s*(?:शताब्दी|सदी)"), "century"),
    (re.compile(r"(\d{1,2})\s*(?:મી|માં)?\s*(?:સદી|શતાબ્દી)"), "century"),
    # "in 1499", "built in 1032", "c. 1063", "circa 1063"
    (re.compile(r"\b(?:in|c\.|circa|year|around|by)\s+(1[0-9]{3}|[5-9][0-9]{2})\b", re.I), "ce"),
]


def extract_dates(text: str) -> list[DateMention]:
    norm = normalise_digits(text)
    found: list[DateMention] = []
    taken: list[tuple[int, int]] = []
    for pattern, kind in _PATTERNS:
        for m in pattern.finditer(norm):
            span = m.span()
            if any(not (span[1] <= a or span[0] >= b) for a, b in taken):
                continue
            num = next(g for g in m.groups() if g and g.strip().isdigit())
            n = int(num)
            if kind == "vs":
                year, cal = n - 57, "vikram-samvat"
            elif kind == "bce":
                year, cal = -n, "gregorian"
            elif kind == "century":
                bce = len(m.groups()) > 1 and bool(m.group(2))
                mid = (n - 1) * 100 + 50
                year, cal = (-mid if bce else mid), "century"
            else:
                year, cal = n, "gregorian"
            if not -4000 <= year <= 2100:
                continue
            taken.append(span)
            found.append(DateMention(text[span[0] : span[1]], year, cal, span[0], span[1]))
    return sorted(found, key=lambda d: d.start)


def format_year(year: int) -> str:
    return f"{-year} BCE" if year < 0 else f"{year} CE"
