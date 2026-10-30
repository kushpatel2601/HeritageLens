"""Upload validation, blob-key safety, images, geo, deck rescue and 3D artifact formats."""

from __future__ import annotations

import asyncio
import io
import struct
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from app.core.errors import UnsupportedMediaError
from app.db.models import AssetKind
from app.services.extractors.files import classify_upload, decode_text
from app.services.extractors.images import dhash, hamming, inspect_image, make_thumbnail
from app.services.extractors.office import MIN_IMAGE_BYTES, extract_docx, extract_pptx
from app.services.geo import bbox_contains, haversine_km, nearest
from app.services.storage import LocalStorage, validate_key
from app.services.twins import (
    PointCloud,
    glb_is_valid,
    kund_stepwell,
    read_ply_header,
    splat_vertex_count,
    vav_stepwell,
    write_ply,
)


def _image(fmt: str = "JPEG", size: tuple[int, int] = (64, 48), seed: int = 1) -> bytes:
    rng = np.random.default_rng(seed)
    img = Image.fromarray(rng.integers(0, 255, (size[1], size[0], 3), dtype=np.uint8))
    buf = io.BytesIO()
    img.save(buf, fmt)
    return buf.getvalue()


class TestClassifyUpload:
    @pytest.mark.parametrize(
        ("name", "data", "declared", "kind"),
        [
            ("vav.jpg", _image(), None, AssetKind.photo),
            ("folio.PNG", _image("PNG"), "scan", AssetKind.scan),
            ("report.pdf", b"%PDF-1.7\n...", None, AssetKind.pdf),
            ("deck.pptx", b"PK\x03\x04rest", None, AssetKind.deck),
            ("notes.docx", b"PK\x03\x04rest", None, AssetKind.journal),
            ("diary.md", b"# Kutch, 1998", None, AssetKind.journal),
            ("legend.txt", b"Once upon a time", "story", AssetKind.story),
        ],
    )
    def test_accepts_by_extension_and_magic(
        self, name: str, data: bytes, declared: str | None, kind: AssetKind
    ) -> None:
        got_kind, mime, ext = classify_upload(name, data, declared)
        assert got_kind == kind
        assert ext == Path(name).suffix.lower()
        assert "/" in mime

    @pytest.mark.parametrize(
        ("name", "data"),
        [
            ("evil.jpg", b"MZ\x90\x00 not an image"),
            ("fake.pdf", _image()),
            ("fake.pptx", b"%PDF-1.4"),
            ("binary.txt", _image("PNG")),
            ("tool.exe", b"MZ\x90\x00"),
        ],
    )
    def test_rejects_spoofed_or_unsupported(self, name: str, data: bytes) -> None:
        with pytest.raises(UnsupportedMediaError):
            classify_upload(name, data)

    def test_decode_text_handles_boms_and_legacy_encodings(self) -> None:
        assert decode_text("\ufeffवाव".encode()) == "वाव"
        assert decode_text("વાવ".encode("utf-16")) == "વાવ"
        assert decode_text("café".encode("cp1252")) == "café"


class TestStorageKeys:
    @pytest.mark.parametrize("key", ["originals/ab/cd.jpg", "twins/site-1/job-2/x.ply", "a"])
    def test_valid(self, key: str) -> None:
        assert validate_key(key) == key

    @pytest.mark.parametrize("key", ["../etc/passwd", "/abs/path", "a/../../b", "", "spaces are bad", "C:\\x"])
    def test_traversal_and_junk_rejected(self, key: str) -> None:
        with pytest.raises(ValueError):
            validate_key(key)

    async def test_local_storage_round_trip(self, tmp_path: Path) -> None:
        store = LocalStorage(tmp_path)
        await store.put("pages/1/p1.png", b"data")
        assert await store.exists("pages/1/p1.png")
        assert await store.get("pages/1/p1.png") == b"data"
        await store.delete("pages/1/p1.png")
        assert not await store.exists("pages/1/p1.png")
        assert not await asyncio.to_thread(lambda: list(tmp_path.rglob("*.tmp")))


class TestImages:
    def test_inspect_and_thumbnail(self) -> None:
        info = inspect_image(_image(size=(1600, 900)))
        assert (info.width, info.height, info.format) == (1600, 900, "jpeg")
        assert info.dhash is not None and len(info.dhash) == 16
        thumb = make_thumbnail(_image(size=(1600, 900)), max_side=320)
        with Image.open(io.BytesIO(thumb)) as t:
            assert (t.format, max(t.size)) == ("WEBP", 320)

    def test_dhash_finds_resized_copies_not_different_images(self) -> None:
        a = Image.open(io.BytesIO(_image(size=(400, 300), seed=3)))
        smaller = a.resize((200, 150))
        other = Image.open(io.BytesIO(_image(size=(400, 300), seed=4)))
        assert hamming(dhash(a), dhash(smaller)) <= 10
        assert hamming(dhash(a), dhash(other)) > 10


@dataclass
class _Place:
    name: str
    lat: float
    lon: float


class TestGeo:
    def test_haversine_patan_to_modhera(self) -> None:
        assert haversine_km(23.8589, 72.1016, 23.5835, 72.1330) == pytest.approx(30.8, abs=0.5)

    def test_nearest_within_radius(self) -> None:
        places = [_Place("Patan", 23.8589, 72.1016), _Place("Modhera", 23.5835, 72.1330)]
        hit = nearest(23.60, 72.13, places, max_km=5)
        assert hit is not None and hit[0].name == "Modhera"
        assert nearest(28.6, 77.2, places, max_km=50) is None

    def test_bbox(self) -> None:
        gujarat = (68.0, 20.0, 75.0, 24.8)
        assert bbox_contains(gujarat, 23.0, 72.5)
        assert not bbox_contains(gujarat, 26.9, 75.8)
        assert not bbox_contains(gujarat, None, 72.5)


class TestOffice:
    def test_pptx_rescues_text_notes_and_photos(self) -> None:
        from pptx import Presentation
        from pptx.util import Inches

        prs = Presentation()
        slide = prs.slides.add_slide(prs.slide_layouts[5])
        slide.shapes.title.text = "Adalaj field visit"
        box = slide.shapes.add_textbox(Inches(1), Inches(2), Inches(4), Inches(1))
        box.text_frame.text = "Five storeys of carved pillars."
        photo = _image(size=(320, 240), seed=9)
        assert len(photo) >= MIN_IMAGE_BYTES
        slide.shapes.add_picture(io.BytesIO(photo), Inches(1), Inches(3))
        slide.shapes.add_picture(io.BytesIO(photo), Inches(5), Inches(3))  # duplicate: kept once
        slide.notes_slide.notes_text_frame.text = "Ask the ASI about the 1499 inscription."
        buf = io.BytesIO()
        prs.save(buf)

        deck = extract_pptx(buf.getvalue())
        [s] = deck.slides
        assert s.title == "Adalaj field visit"
        assert "carved pillars" in s.text
        assert "Notes: Ask the ASI" in s.as_text()
        [img] = deck.images
        assert (img.slide_no, img.ext, img.caption) == (1, ".jpg", "Adalaj field visit")

    def test_docx_paragraphs_and_tables(self) -> None:
        from docx import Document

        doc = Document()
        doc.add_paragraph("Survey of Chand Baori")
        table = doc.add_table(rows=1, cols=2)
        table.rows[0].cells[0].text = "Steps"
        table.rows[0].cells[1].text = "3500"
        buf = io.BytesIO()
        doc.save(buf)
        assert extract_docx(buf.getvalue()) == "Survey of Chand Baori\n\nSteps | 3500"


class TestTwinFormats:
    def test_ply_round_trip(self) -> None:
        cloud = PointCloud(
            xyz=np.array([[0, 0, 0], [1, 2, 3]], dtype=np.float32), rgb=np.array([[255, 0, 0], [0, 0, 255]], np.uint8)
        )
        data = write_ply(cloud)
        header = read_ply_header(data)
        assert header == {
            "format": "binary_little_endian",
            "vertex_count": 2,
            "properties": ["x", "y", "z", "red", "green", "blue"],
        }
        body = data[data.index(b"end_header\n") + len(b"end_header\n") :]
        assert len(body) == 2 * (3 * 4 + 3)
        assert struct.unpack_from("<3f", body, 15) == (1.0, 2.0, 3.0)

    @pytest.mark.parametrize("builder", [kund_stepwell, vav_stepwell])
    def test_procedural_stepwells_are_deterministic(self, builder: Callable[[], PointCloud]) -> None:
        a, b = builder(), builder()
        assert len(a) > 1000
        assert np.array_equal(a.xyz, b.xyz)
        assert a.xyz.dtype == np.float32 and a.rgb.dtype == np.uint8

    def test_invalid_artifacts(self) -> None:
        with pytest.raises(ValueError):
            read_ply_header(b"not a ply")
        with pytest.raises(ValueError):
            splat_vertex_count(b"x" * 33)
        assert splat_vertex_count(b"x" * 64) == 2
        assert glb_is_valid(b"glTF" + struct.pack("<II", 2, 12))
        assert not glb_is_valid(b"glTF" + struct.pack("<II", 1, 12))
