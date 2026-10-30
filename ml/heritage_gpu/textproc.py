"""Model-agnostic text utilities: sentence segmentation for MT, OCR text assembly and clean-up."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable, Sequence
from typing import Any

# Sentence terminators: Latin punctuation, the Devanagari danda / double danda (also used in
# Gujarati, Bengali, ...) and the Urdu full stop.
_SENTENCE_END = re.compile(r"(?<=[.!?\u0964\u0965\u06d4])\s+|\n+")
_SOFT_BREAK = re.compile(r"(?<=[,;:\u060c])\s+")
_SPACES = re.compile(r"[ \t\u00a0]+")

# BLIP's best-known artefact: "arafed"/"araffe" hallucinated tokens at caption start.
_BLIP_JUNK = re.compile(r"\b(?:araf+e?d?|arafe|araffe)\b\s*", re.IGNORECASE)


def normalize(text: str) -> str:
    """NFC (Indic OCR often emits decomposed nukta / matra sequences), tidy spaces, keep newlines."""
    text = unicodedata.normalize("NFC", text).replace("\r\n", "\n").replace("\r", "\n")
    lines = [_SPACES.sub(" ", line).strip() for line in text.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def split_sentences(text: str, max_chars: int = 400) -> list[str]:
    """Split into translation units. Over-long sentences are cut at clause boundaries, then at word
    boundaries, so no unit is silently truncated by the model's max input length."""
    units: list[str] = []
    for sentence in _SENTENCE_END.split(text):
        sentence = sentence.strip()
        if not sentence:
            continue
        if len(sentence) <= max_chars:
            units.append(sentence)
            continue
        buf = ""
        for clause in _SOFT_BREAK.split(sentence):
            for piece in _wrap(clause, max_chars):
                if buf and len(buf) + 1 + len(piece) > max_chars:
                    units.append(buf)
                    buf = piece
                else:
                    buf = f"{buf} {piece}".strip()
        if buf:
            units.append(buf)
    return units


def _wrap(text: str, width: int) -> list[str]:
    out, line = [], ""
    for word in text.split():
        if line and len(line) + 1 + len(word) > width:
            out.append(line)
            line = word
        else:
            line = f"{line} {word}".strip()
    if line:
        out.append(line)
    return out


def translate_documents(
    texts: Sequence[str], translate: Callable[[list[str]], list[str]], *, batch_size: int = 16, max_chars: int = 400
) -> list[str]:
    """Translate many multi-sentence texts with one batched, length-sorted pass over all sentences.

    Sorting by length keeps padding (and so GPU time) low; results are scattered back into the
    original order and re-joined per text.
    """
    units: list[tuple[int, str]] = [(i, s) for i, t in enumerate(texts) for s in split_sentences(t, max_chars)]
    order = sorted(range(len(units)), key=lambda k: len(units[k][1]), reverse=True)
    translated: list[str] = [""] * len(units)
    for start in range(0, len(order), batch_size):
        idx = order[start : start + batch_size]
        outputs = translate([units[k][1] for k in idx])
        if len(outputs) != len(idx):
            raise RuntimeError(f"translator returned {len(outputs)} outputs for {len(idx)} inputs")
        for k, out in zip(idx, outputs, strict=True):
            translated[k] = out.strip()
    per_text: list[list[str]] = [[] for _ in texts]
    for (i, _), out in zip(units, translated, strict=True):
        if out:
            per_text[i].append(out)
    return [" ".join(parts) for parts in per_text]


def assemble_tesseract(data: dict[str, list[Any]]) -> tuple[str, float | None]:
    """Rebuild text and mean word confidence from one ``image_to_data`` call (instead of running
    recognition twice for ``image_to_string`` + ``image_to_data``)."""
    lines: dict[tuple[int, int, int], list[str]] = {}
    confs: list[float] = []
    for i, word in enumerate(data.get("text", [])):
        word = str(word).strip()
        if not word:
            continue
        key = (int(data["block_num"][i]), int(data["par_num"][i]), int(data["line_num"][i]))
        lines.setdefault(key, []).append(word)
        try:
            conf = float(data["conf"][i])
        except (TypeError, ValueError):
            continue
        if conf >= 0:
            confs.append(conf)
    out: list[str] = []
    prev: tuple[int, int] | None = None
    for (block, par, _line), words in sorted(lines.items()):
        if prev is not None and prev != (block, par):
            out.append("")  # paragraph break
        out.append(" ".join(words))
        prev = (block, par)
    text = normalize("\n".join(out))
    return text, (round(sum(confs) / len(confs) / 100.0, 4) if confs else None)


def clean_caption(text: str, prompt: str = "") -> str:
    """Drop BLIP artefacts and the conditioning prompt ("a photograph of" adds nothing to search)."""
    text = _BLIP_JUNK.sub("", text).strip()
    if prompt and text.lower().startswith(prompt.lower().strip()):
        text = text[len(prompt.strip()) :].strip()
    text = _SPACES.sub(" ", text).strip(" .,")
    return text[:1].upper() + text[1:] if text else ""
