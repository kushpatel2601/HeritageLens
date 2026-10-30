from __future__ import annotations

from pathlib import PurePath

from app.core.errors import UnsupportedMediaError
from app.db.models import AssetKind

_IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff"}
_TEXT_EXT = {".txt", ".md", ".markdown"}

_MIME = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".pdf": "application/pdf",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".txt": "text/plain; charset=utf-8",
    ".md": "text/markdown; charset=utf-8",
    ".markdown": "text/markdown; charset=utf-8",
}


def _sniff(data: bytes) -> str | None:
    head = data[:16]
    if head.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    if head[:4] in (b"II*\x00", b"MM\x00*"):
        return "tiff"
    if head.startswith(b"%PDF"):
        return "pdf"
    if head.startswith(b"PK\x03\x04"):
        return "zip"
    return None


def classify_upload(filename: str, data: bytes, declared: str | None = None) -> tuple[AssetKind, str, str]:
    """Return (kind, mime, extension) after validating magic bytes against the extension."""
    ext = PurePath(filename).suffix.lower()
    sniffed = _sniff(data)
    if ext in _IMAGE_EXT:
        if sniffed not in ("jpeg", "png", "webp", "tiff"):
            raise UnsupportedMediaError(f"{filename}: content is not a valid image")
        kind = AssetKind.scan if declared == AssetKind.scan else AssetKind.photo
    elif ext == ".pdf":
        if sniffed != "pdf":
            raise UnsupportedMediaError(f"{filename}: content is not a PDF")
        kind = AssetKind.pdf
    elif ext == ".pptx":
        if sniffed != "zip":
            raise UnsupportedMediaError(f"{filename}: content is not a PPTX")
        kind = AssetKind.deck
    elif ext == ".docx" or ext in _TEXT_EXT:
        if ext == ".docx" and sniffed != "zip":
            raise UnsupportedMediaError(f"{filename}: content is not a DOCX")
        if ext in _TEXT_EXT and sniffed is not None:
            raise UnsupportedMediaError(f"{filename}: binary content in a text file")
        kind = AssetKind.story if declared == AssetKind.story else AssetKind.journal
    else:
        raise UnsupportedMediaError(f"{filename}: unsupported type. Accepted: images, PDF, PPTX, DOCX, TXT, MD")
    return kind, _MIME[ext], ext


def decode_text(data: bytes) -> str:
    if data.startswith(b"\xef\xbb\xbf"):
        return data[3:].decode("utf-8", errors="replace")
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16", errors="replace")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")
