"""Rescue content trapped in presentation decks and Word reports - the archive 'graveyard'."""

from __future__ import annotations

import hashlib
import io
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

MIN_IMAGE_BYTES = 12_000  # skip logos, bullets and decorative glyphs


@dataclass(slots=True)
class Slide:
    number: int
    title: str
    text: str
    notes: str

    def as_text(self) -> str:
        parts = [p for p in (self.title, self.text, self.notes and f"Notes: {self.notes}") if p]
        return "\n\n".join(parts)


@dataclass(slots=True)
class EmbeddedImage:
    slide_no: int
    data: bytes
    ext: str
    caption: str


@dataclass(slots=True)
class DeckContent:
    slides: list[Slide] = field(default_factory=list)
    images: list[EmbeddedImage] = field(default_factory=list)


def _walk(shapes: Any) -> Iterator[Any]:
    from pptx.enum.shapes import MSO_SHAPE_TYPE

    for shape in shapes:
        if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
            yield from _walk(shape.shapes)
        else:
            yield shape


def extract_pptx(data: bytes) -> DeckContent:
    from pptx import Presentation
    from pptx.enum.shapes import MSO_SHAPE_TYPE

    prs = Presentation(io.BytesIO(data))
    out = DeckContent()
    seen: set[str] = set()
    for idx, slide in enumerate(prs.slides, start=1):
        title_shape = slide.shapes.title
        title = title_shape.text_frame.text.strip() if title_shape is not None and title_shape.has_text_frame else ""
        texts: list[str] = []
        for shape in _walk(slide.shapes):
            if shape is title_shape:
                continue
            if getattr(shape, "has_text_frame", False) and shape.text_frame.text.strip():
                texts.append(shape.text_frame.text.strip())
            elif getattr(shape, "has_table", False):
                for row in shape.table.rows:
                    cells = [c.text.strip() for c in row.cells if c.text.strip()]
                    if cells:
                        texts.append(" | ".join(cells))
            if shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
                try:
                    blob, ext = shape.image.blob, shape.image.ext
                except Exception:
                    continue
                digest = hashlib.sha256(blob).hexdigest()
                if len(blob) >= MIN_IMAGE_BYTES and digest not in seen:
                    seen.add(digest)
                    out.images.append(EmbeddedImage(idx, blob, "." + ext.lower().lstrip("."), title or f"Slide {idx}"))
        notes = ""
        if slide.has_notes_slide and slide.notes_slide.notes_text_frame is not None:
            notes = slide.notes_slide.notes_text_frame.text.strip()
        out.slides.append(Slide(idx, title, "\n".join(texts), notes))
    return out


def extract_docx(data: bytes) -> str:
    from docx import Document

    doc = Document(io.BytesIO(data))
    parts = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
    for table in doc.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells if c.text.strip()]
            if cells:
                parts.append(" | ".join(cells))
    return "\n\n".join(parts)
