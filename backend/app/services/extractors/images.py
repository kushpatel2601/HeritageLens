from __future__ import annotations

import io
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from PIL import ExifTags, Image, ImageOps

Image.MAX_IMAGE_PIXELS = 120_000_000  # decompression-bomb guard (~120 MP)

_GPS_IFD = 0x8825
_EXIF_IFD = 0x8769


@dataclass(slots=True)
class ImageInfo:
    width: int
    height: int
    format: str
    lat: float | None = None
    lon: float | None = None
    captured_at: datetime | None = None
    camera: str | None = None
    dhash: str | None = None


def _ratio(v: Any) -> float:
    try:
        return float(v)
    except TypeError:
        num, den = v
        return float(num) / float(den or 1)


def _dms_to_deg(dms: Any, ref: str | None) -> float | None:
    try:
        d, m, s = (_ratio(x) for x in dms)
    except Exception:
        return None
    deg = d + m / 60 + s / 3600
    return -deg if ref in ("S", "W") else deg


def read_exif(img: Image.Image) -> tuple[float | None, float | None, datetime | None, str | None]:
    exif = img.getexif()
    if not exif:
        return None, None, None, None
    lat = lon = None
    gps = exif.get_ifd(_GPS_IFD)
    if gps:
        lat = _dms_to_deg(gps.get(2), gps.get(1))
        lon = _dms_to_deg(gps.get(4), gps.get(3))
        if lat is not None and lon is not None and not (-90 <= lat <= 90 and -180 <= lon <= 180):
            lat = lon = None
    captured = None
    raw_dt = exif.get_ifd(_EXIF_IFD).get(36867) or exif.get(ExifTags.Base.DateTime)
    if isinstance(raw_dt, str):
        try:
            captured = datetime.strptime(raw_dt.strip(), "%Y:%m:%d %H:%M:%S").replace(tzinfo=UTC)
        except ValueError:
            captured = None
    make, model = exif.get(ExifTags.Base.Make), exif.get(ExifTags.Base.Model)
    camera = " ".join(str(x).strip() for x in (make, model) if x) or None
    return lat, lon, captured, camera


def dhash(img: Image.Image, size: int = 8) -> str:
    """64-bit difference hash - near-duplicate detection across re-uploads / resized copies."""
    g = img.convert("L").resize((size + 1, size), Image.Resampling.LANCZOS)
    px = g.tobytes()  # mode "L": one byte per pixel, row-major
    bits = 0
    for row in range(size):
        for col in range(size):
            left = px[row * (size + 1) + col]
            right = px[row * (size + 1) + col + 1]
            bits = (bits << 1) | (1 if left > right else 0)
    return f"{bits:016x}"


def hamming(a: str, b: str) -> int:
    return (int(a, 16) ^ int(b, 16)).bit_count()


def inspect_image(data: bytes) -> ImageInfo:
    with Image.open(io.BytesIO(data)) as src:
        lat, lon, captured, camera = read_exif(src)
        fmt = (src.format or "").lower()
        img = ImageOps.exif_transpose(src)
        return ImageInfo(
            width=img.width,
            height=img.height,
            format=fmt,
            lat=lat,
            lon=lon,
            captured_at=captured,
            camera=camera,
            dhash=dhash(img),
        )


def make_thumbnail(data: bytes, max_side: int = 720, quality: int = 80) -> bytes:
    with Image.open(io.BytesIO(data)) as src:
        img = ImageOps.exif_transpose(src)
        img.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGB")
        out = io.BytesIO()
        img.save(out, "WEBP", quality=quality, method=4)
        return out.getvalue()


def to_png(data: bytes) -> bytes:
    with Image.open(io.BytesIO(data)) as src:
        img = ImageOps.exif_transpose(src)
        out = io.BytesIO()
        img.convert("RGB").save(out, "PNG")
        return out.getvalue()
