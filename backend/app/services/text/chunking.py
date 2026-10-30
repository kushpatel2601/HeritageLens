from __future__ import annotations

import re
from dataclasses import dataclass

# Sentence boundaries for Latin + Indic (danda । and double danda ॥).
_SENTENCE_END = re.compile(r"(?<=[.!?।॥])\s+")


@dataclass(frozen=True, slots=True)
class TextChunk:
    text: str
    start: int
    seq: int
    overlap: int = 0  # leading chars repeated from the previous chunk for retrieval context

    @property
    def body(self) -> str:
        """The chunk without the carried-over context."""
        return self.text[self.overlap :].lstrip()


def chunk_text(text: str, max_chars: int = 700, overlap: int = 120) -> list[TextChunk]:
    """Paragraph-first, sentence-aware chunking with a soft overlap for retrieval context."""
    text = text.replace("\r\n", "\n").strip()
    if not text:
        return []
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    units: list[str] = []
    for p in paragraphs:
        if len(p) <= max_chars:
            units.append(p)
            continue
        sentences = _SENTENCE_END.split(p)
        for s in sentences:
            while len(s) > max_chars:  # pathological run-on: hard wrap on whitespace
                cut = s.rfind(" ", 0, max_chars)
                cut = cut if cut > max_chars // 2 else max_chars
                units.append(s[:cut].strip())
                s = s[cut:].strip()
            if s:
                units.append(s)

    chunks: list[TextChunk] = []
    buf = ""
    carried = 0
    for unit in units:
        candidate = f"{buf}\n\n{unit}" if buf else unit
        if len(candidate) <= max_chars:
            buf = candidate
            continue
        if buf:
            chunks.append(_make(text, buf, carried, len(chunks)))
            tail = buf[-overlap:] if overlap else ""
            tail = tail[tail.find(" ") + 1 :].strip() if " " in tail else tail.strip()
            buf, carried = (f"{tail} {unit}", len(tail)) if tail else (unit, 0)
        else:
            buf, carried = unit, 0
    if buf:
        chunks.append(_make(text, buf, carried, len(chunks)))
    return chunks


def _make(full: str, chunk: str, carried: int, seq: int) -> TextChunk:
    """`start` is the offset of the chunk's new content (after any carried-over context)."""
    pos = full.find(chunk[carried:].lstrip()[:40])
    return TextChunk(text=chunk, start=max(pos, 0), seq=seq, overlap=carried)
