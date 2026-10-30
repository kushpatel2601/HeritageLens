from __future__ import annotations

import io
from dataclasses import dataclass

MIN_TEXT_CHARS = 25  # below this a page is treated as a scanned image that needs OCR


@dataclass(slots=True)
class PdfPage:
    page_no: int
    text: str
    needs_ocr: bool
    image_png: bytes | None = None


def extract_pdf(data: bytes, max_pages: int = 400, render_scale: float = 2.5) -> list[PdfPage]:
    """Text layer via pypdf; image-only pages are rasterised (pdfium) for the OCR stage."""
    import pypdfium2 as pdfium
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    pdf = pdfium.PdfDocument(data)
    pages: list[PdfPage] = []
    try:
        for i, page in enumerate(reader.pages[:max_pages]):
            try:
                text = (page.extract_text() or "").strip()
            except Exception:
                text = ""
            needs_ocr = len(text) < MIN_TEXT_CHARS
            image_png = None
            if needs_ocr or i == 0:
                bitmap = pdf[i].render(scale=render_scale if needs_ocr else 1.0)
                buf = io.BytesIO()
                bitmap.to_pil().convert("RGB").save(buf, "PNG", optimize=True)
                image_png = buf.getvalue()
            pages.append(PdfPage(page_no=i + 1, text=text, needs_ocr=needs_ocr, image_png=image_png))
    finally:
        pdf.close()
    return pages
