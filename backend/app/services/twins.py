"""Procedural 3D twins and PLY I/O.

The seed archive ships parametric point clouds of the two canonical stepwell typologies (a stepped
*kund* pond and a linear *vav* with pillared pavilions) so the 3D viewer works out of the box. Real
twins are produced by the GPU worker (monocular depth relief or Gaussian splatting) from contributor
photos and stored through the same `Twin` model.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

import numpy as np

SANDSTONE = np.array([196, 150, 98], dtype=np.float32)
SANDSTONE_DARK = np.array([120, 86, 54], dtype=np.float32)
WATER = np.array([46, 92, 110], dtype=np.float32)
GROUND = np.array([164, 140, 104], dtype=np.float32)


@dataclass(slots=True)
class PointCloud:
    xyz: np.ndarray  # (N, 3) float32, y-up
    rgb: np.ndarray  # (N, 3) uint8

    def __len__(self) -> int:
        return int(self.xyz.shape[0])


class _Builder:
    def __init__(self, seed: int) -> None:
        self.rng = np.random.default_rng(seed)
        self.xyz: list[np.ndarray] = []
        self.rgb: list[np.ndarray] = []

    def add(self, pts: np.ndarray, base: np.ndarray, jitter: float = 14.0) -> None:
        noise = self.rng.normal(0.0, jitter, size=(len(pts), 1)).astype(np.float32)
        self.xyz.append(pts.astype(np.float32))
        self.rgb.append(np.clip(base[None, :] + noise, 0, 255))

    def rect_h(self, x0: float, x1: float, z0: float, z1: float, y: float, n: int, color: np.ndarray) -> None:
        """Horizontal rectangle (tread / floor slab)."""
        pts = np.column_stack([self.rng.uniform(x0, x1, n), np.full(n, y), self.rng.uniform(z0, z1, n)])
        self.add(pts, color)

    def rect_v(
        self, a: tuple[float, float], b: tuple[float, float], y0: float, y1: float, n: int, color: np.ndarray
    ) -> None:
        """Vertical wall between two (x, z) points."""
        t = self.rng.uniform(0, 1, n)
        x = a[0] + (b[0] - a[0]) * t
        z = a[1] + (b[1] - a[1]) * t
        pts = np.column_stack([x, self.rng.uniform(y0, y1, n), z])
        self.add(pts, color)

    def cylinder(self, cx: float, cz: float, r: float, y0: float, y1: float, n: int, color: np.ndarray) -> None:
        th = self.rng.uniform(0, 2 * np.pi, n)
        pts = np.column_stack([cx + r * np.cos(th), self.rng.uniform(y0, y1, n), cz + r * np.sin(th)])
        self.add(pts, color)

    def build(self) -> PointCloud:
        xyz = np.concatenate(self.xyz)
        rgb = np.concatenate(self.rgb).astype(np.uint8)
        xyz -= xyz.mean(axis=0, keepdims=True) * np.array([1, 0, 1], dtype=np.float32)
        return PointCloud(xyz=xyz, rgb=rgb)


def _shade(depth_frac: float) -> np.ndarray:
    return SANDSTONE * (1 - depth_frac) + SANDSTONE_DARK * depth_frac


def kund_stepwell(levels: int = 11, top: float = 12.0, seed: int = 7, density: int = 1400) -> PointCloud:
    """Square stepped tank (Chand Baori / Adalaj kund typology): concentric terraces down to water."""
    b = _Builder(seed)
    step = top / (levels + 2)
    rise = 0.55
    for i in range(levels):
        outer, inner = top - i * step, top - (i + 1) * step
        y = -i * rise
        frac = i / max(levels - 1, 1)
        color = _shade(frac)
        n = int(density * (outer / top) ** 2)
        for sx0, sx1, sz0, sz1 in (
            (-outer, outer, inner, outer),
            (-outer, outer, -outer, -inner),
            (-outer, -inner, -inner, inner),
            (inner, outer, -inner, inner),
        ):
            b.rect_h(sx0, sx1, sz0, sz1, y, n // 2, color)
        # risers with the zig-zag flights rendered as alternating light/dark bands
        for a, c in (
            ((-inner, -inner), (inner, -inner)),
            ((inner, -inner), (inner, inner)),
            ((inner, inner), (-inner, inner)),
            ((-inner, inner), (-inner, -inner)),
        ):
            b.rect_v(a, c, y - rise, y, n // 3, color * (0.82 if i % 2 else 0.95))
    b.rect_h(
        -top + levels * step,
        top - levels * step,
        -top + levels * step,
        top - levels * step,
        -levels * rise + 0.05,
        density,
        WATER,
    )
    # ground apron and a parapet
    b.rect_h(-top * 1.35, top * 1.35, top, top * 1.35, 0.0, density, GROUND)
    b.rect_h(-top * 1.35, top * 1.35, -top * 1.35, -top, 0.0, density, GROUND)
    b.rect_h(-top * 1.35, -top, -top, top, 0.0, density // 2, GROUND)
    b.rect_h(top, top * 1.35, -top, top, 0.0, density // 2, GROUND)
    for a, c in (((-top, -top), (top, -top)), ((top, -top), (top, top)), ((-top, top), (-top, -top))):
        b.rect_v(a, c, 0.0, 0.9, density // 3, SANDSTONE * 1.05)
    return b.build()


def vav_stepwell(pavilions: int = 5, seed: int = 11, density: int = 1600) -> PointCloud:
    """Linear stepwell (Rani ki Vav / Adalaj typology): a stepped corridor descending through
    multi-storey pillared pavilions (kutas) to a cylindrical well shaft."""
    b = _Builder(seed)
    width, bay, rise_per_bay = 6.0, 6.0, 2.2
    length = pavilions * bay
    for p in range(pavilions):
        x0 = p * bay
        y_floor = -p * rise_per_bay
        frac = p / max(pavilions - 1, 1)
        color = _shade(frac)
        # treads descending inside the bay
        for s in range(8):
            xs = x0 + s * bay / 8
            b.rect_h(xs, xs + bay / 8, -width / 2, width / 2, y_floor - s * rise_per_bay / 8, density // 8, color)
        # side walls with carved niches suggested by banded shading
        for z in (-width / 2, width / 2):
            for band in range(4):
                b.rect_v(
                    (x0, z),
                    (x0 + bay, z),
                    y_floor - rise_per_bay + band * 1.5,
                    y_floor - rise_per_bay + (band + 1) * 1.5,
                    density // 6,
                    color * (0.9 if band % 2 else 1.02),
                )
        # pavilion: pillars and stacked floor slabs reaching ground level
        storeys = p + 1
        for k in range(storeys):
            ys = y_floor + k * rise_per_bay
            if ys > 0.01:
                break
            for px in (x0 + 0.6, x0 + bay - 0.6):
                for pz in (-width / 2 + 0.6, -0.9, 0.9, width / 2 - 0.6):
                    b.cylinder(px, pz, 0.22, ys, ys + rise_per_bay - 0.25, density // 20, color * 1.04)
            b.rect_h(
                x0 + 0.3, x0 + bay - 0.3, -width / 2, width / 2, ys + rise_per_bay - 0.2, density // 3, color * 0.97
            )
    # well shaft
    shaft_x, depth = length + 3.5, pavilions * rise_per_bay + 6
    b.cylinder(shaft_x, 0.0, 3.2, -depth, 0.0, density * 3, SANDSTONE_DARK * 1.05)
    r = np.sqrt(b.rng.uniform(0, 1, density)) * 3.1
    a = b.rng.uniform(0, 2 * np.pi, density)
    b.add(np.column_stack([shaft_x + r * np.cos(a), np.full(density, -depth + 1.0), r * np.sin(a)]), WATER)
    # ground around the trench
    b.rect_h(-3, length + 8, width / 2, width / 2 + 5, 0.0, density * 2, GROUND)
    b.rect_h(-3, length + 8, -width / 2 - 5, -width / 2, 0.0, density * 2, GROUND)
    return b.build()


def write_ply(cloud: PointCloud, comment: str = "HeritageLens") -> bytes:
    """Binary little-endian PLY with float xyz and uchar rgb (three.js PLYLoader compatible)."""
    n = len(cloud)
    header = (
        "ply\nformat binary_little_endian 1.0\n"
        f"comment {comment}\n"
        f"element vertex {n}\n"
        "property float x\nproperty float y\nproperty float z\n"
        "property uchar red\nproperty uchar green\nproperty uchar blue\n"
        "end_header\n"
    ).encode("ascii")
    rec = np.empty(n, dtype=[("x", "<f4"), ("y", "<f4"), ("z", "<f4"), ("r", "u1"), ("g", "u1"), ("b", "u1")])
    rec["x"], rec["y"], rec["z"] = cloud.xyz[:, 0], cloud.xyz[:, 1], cloud.xyz[:, 2]
    rec["r"], rec["g"], rec["b"] = cloud.rgb[:, 0], cloud.rgb[:, 1], cloud.rgb[:, 2]
    return header + rec.tobytes()


def read_ply_header(data: bytes) -> dict[str, object]:
    """Validate an uploaded PLY and return {format, vertex_count, properties}."""
    end = data.find(b"end_header\n")
    if not data.startswith(b"ply\n") or end < 0:
        raise ValueError("not a PLY file")
    lines = data[:end].decode("ascii", "replace").splitlines()
    fmt, count, props = "", 0, []
    for line in lines:
        parts = line.split()
        if parts[:1] == ["format"]:
            fmt = parts[1]
        elif parts[:2] == ["element", "vertex"]:
            count = int(parts[2])
        elif parts[:1] == ["property"]:
            props.append(parts[-1])
    return {"format": fmt, "vertex_count": count, "properties": props}


def splat_vertex_count(data: bytes) -> int:
    """antimatter15 .splat: 32 bytes per gaussian."""
    if len(data) % 32:
        raise ValueError("not a .splat file (size is not a multiple of 32)")
    return len(data) // 32


def glb_is_valid(data: bytes) -> bool:
    return len(data) >= 12 and data[:4] == b"glTF" and struct.unpack("<I", data[4:8])[0] == 2
