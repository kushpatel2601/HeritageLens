"""Pure-numpy 3D geometry for digital twins (no torch, fully unit-tested).

* :func:`relief_from_disparity` lifts a monocular depth map into a coloured point cloud.
* :func:`write_ply` / :func:`write_splat` serialise point clouds and Gaussian splats in the two
  formats the HeritageLens viewer streams (binary PLY, antimatter15 ``.splat``).
* :class:`Similarity` moves COLMAP's arbitrary world frame into the viewer's frame (y-up, centred,
  normalised scale), rotating Gaussian orientations consistently with their centres.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

SH_C0 = 0.28209479177387814  # zeroth-order spherical-harmonic basis constant
VIEWER_RADIUS = 10.0  # procedural seed twins are ~10-30 units across; keep uploads comparable


@dataclass(slots=True)
class PointCloud:
    xyz: np.ndarray  # (N, 3) float32, y-up
    rgb: np.ndarray  # (N, 3) uint8

    def __post_init__(self) -> None:
        if self.xyz.ndim != 2 or self.xyz.shape[1] != 3 or self.rgb.shape != self.xyz.shape:
            raise ValueError(f"bad point cloud shapes {self.xyz.shape} / {self.rgb.shape}")

    def __len__(self) -> int:
        return int(self.xyz.shape[0])


# ---------------------------------------------------------------- serialisation
def write_ply(cloud: PointCloud, comment: str = "HeritageLens") -> bytes:
    """Binary little-endian PLY, float xyz + uchar rgb (three.js ``PLYLoader`` compatible)."""
    n = len(cloud)
    safe_comment = " ".join(comment.split())
    header = (
        "ply\nformat binary_little_endian 1.0\n"
        f"comment {safe_comment}\n"
        f"element vertex {n}\n"
        "property float x\nproperty float y\nproperty float z\n"
        "property uchar red\nproperty uchar green\nproperty uchar blue\n"
        "end_header\n"
    ).encode("ascii", "replace")
    rec = np.empty(n, dtype=[("x", "<f4"), ("y", "<f4"), ("z", "<f4"), ("r", "u1"), ("g", "u1"), ("b", "u1")])
    rec["x"], rec["y"], rec["z"] = cloud.xyz[:, 0], cloud.xyz[:, 1], cloud.xyz[:, 2]
    rec["r"], rec["g"], rec["b"] = cloud.rgb[:, 0], cloud.rgb[:, 1], cloud.rgb[:, 2]
    return header + rec.tobytes()


SPLAT_DTYPE = np.dtype([("pos", "<f4", 3), ("scale", "<f4", 3), ("rgba", "u1", 4), ("rot", "u1", 4)])
assert SPLAT_DTYPE.itemsize == 32


def write_splat(
    means: np.ndarray, scales: np.ndarray, quats_wxyz: np.ndarray, rgb: np.ndarray, alpha: np.ndarray
) -> bytes:
    """antimatter15 ``.splat``: 32 bytes per Gaussian, largest/most opaque first.

    ``scales`` are linear (not log), ``rgb``/``alpha`` in [0, 1], quaternions w-first.
    """
    n = means.shape[0]
    if not (scales.shape == means.shape == rgb.shape and quats_wxyz.shape == (n, 4) and alpha.shape == (n,)):
        raise ValueError("inconsistent gaussian attribute shapes")
    order = np.argsort(-(np.prod(scales, axis=1) * alpha), kind="stable")
    q = quats_wxyz / np.clip(np.linalg.norm(quats_wxyz, axis=1, keepdims=True), 1e-12, None)
    rec = np.empty(n, dtype=SPLAT_DTYPE)
    rec["pos"] = means[order]
    rec["scale"] = scales[order]
    rgba = np.concatenate([rgb[order], alpha[order, None]], axis=1)
    rec["rgba"] = np.clip(np.round(rgba * 255), 0, 255).astype(np.uint8)
    rec["rot"] = np.clip(np.round(q[order] * 128 + 128), 0, 255).astype(np.uint8)
    return rec.tobytes()


# ---------------------------------------------------------------- monocular depth relief
def relief_from_disparity(
    rgb: np.ndarray,
    disparity: np.ndarray,
    *,
    fov_deg: float = 55.0,
    max_points: int = 600_000,
    depth_range: tuple[float, float] = (1.0, 4.0),
    min_disparity: float = 0.03,
    edge_tolerance: float = 0.05,
) -> PointCloud:
    """Back-project a relative inverse-depth map (Depth-Anything style) into a coloured relief.

    Monocular models predict affine-invariant *disparity*, so we normalise it robustly, map it to a
    bounded depth range by interpolating in inverse depth, drop the far background (sky) and
    "flying pixels" on depth discontinuities, then sample on a regular grid to ``max_points``.
    """
    if rgb.ndim != 3 or rgb.shape[2] != 3 or rgb.shape[:2] != disparity.shape:
        raise ValueError(f"rgb {rgb.shape} and disparity {disparity.shape} do not match")
    H, W = disparity.shape
    d = disparity.astype(np.float64)
    lo, hi = np.percentile(d, [1.0, 99.0])
    if not np.isfinite(hi - lo) or hi - lo < 1e-6:
        raise ValueError("depth map is flat - nothing to reconstruct")
    dn = np.clip((d - lo) / (hi - lo), 0.0, 1.0)  # 1 = nearest
    near, far = depth_range
    z = 1.0 / (dn / near + (1.0 - dn) / far)

    jump = np.zeros_like(z)
    jump[1:, :] = np.maximum(jump[1:, :], np.abs(np.diff(z, axis=0)))
    jump[:, 1:] = np.maximum(jump[:, 1:], np.abs(np.diff(z, axis=1)))
    keep = (dn > min_disparity) & (jump / z < edge_tolerance)

    step = max(1, math.ceil(math.sqrt(max(int(keep.sum()), 1) / max_points)))
    vs, us = np.mgrid[0:H:step, 0:W:step]
    sel = keep[vs, us]
    u, v = us[sel].astype(np.float64), vs[sel].astype(np.float64)
    zz = z[vs[sel], us[sel]]
    if zz.size < 16:
        raise ValueError("too few points survived filtering")

    f = 0.5 * W / math.tan(math.radians(fov_deg) / 2)
    xyz = np.column_stack([(u - W / 2 + 0.5) * zz / f, -(v - H / 2 + 0.5) * zz / f, -zz])
    xyz -= xyz.mean(axis=0)
    radius = float(np.percentile(np.linalg.norm(xyz, axis=1), 98)) or 1.0
    xyz *= VIEWER_RADIUS / radius
    colours = rgb[vs[sel], us[sel]].astype(np.uint8)
    return PointCloud(xyz=xyz.astype(np.float32), rgb=colours)


# ---------------------------------------------------------------- rotations & frames
def quat_multiply(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Hamilton product of w-first quaternions; broadcasts over leading dimensions."""
    aw, ax, ay, az = np.moveaxis(a, -1, 0)
    bw, bx, by, bz = np.moveaxis(b, -1, 0)
    return np.stack(
        [
            aw * bw - ax * bx - ay * by - az * bz,
            aw * bx + ax * bw + ay * bz - az * by,
            aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw,
        ],
        axis=-1,
    )


def quat_to_matrix(q: np.ndarray) -> np.ndarray:
    w, x, y, z = q / np.linalg.norm(q)
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
            [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
            [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)],
        ]
    )


def matrix_to_quat(R: np.ndarray) -> np.ndarray:
    """Rotation matrix -> unit quaternion (w-first, w >= 0), numerically stable branch selection."""
    m = np.asarray(R, dtype=np.float64)
    tr = np.trace(m)
    if tr > 0:
        s = math.sqrt(tr + 1.0) * 2
        q = [0.25 * s, (m[2, 1] - m[1, 2]) / s, (m[0, 2] - m[2, 0]) / s, (m[1, 0] - m[0, 1]) / s]
    elif m[0, 0] > m[1, 1] and m[0, 0] > m[2, 2]:
        s = math.sqrt(1.0 + m[0, 0] - m[1, 1] - m[2, 2]) * 2
        q = [(m[2, 1] - m[1, 2]) / s, 0.25 * s, (m[0, 1] + m[1, 0]) / s, (m[0, 2] + m[2, 0]) / s]
    elif m[1, 1] > m[2, 2]:
        s = math.sqrt(1.0 + m[1, 1] - m[0, 0] - m[2, 2]) * 2
        q = [(m[0, 2] - m[2, 0]) / s, (m[0, 1] + m[1, 0]) / s, 0.25 * s, (m[1, 2] + m[2, 1]) / s]
    else:
        s = math.sqrt(1.0 + m[2, 2] - m[0, 0] - m[1, 1]) * 2
        q = [(m[1, 0] - m[0, 1]) / s, (m[0, 2] + m[2, 0]) / s, (m[1, 2] + m[2, 1]) / s, 0.25 * s]
    out = np.array(q)
    out /= np.linalg.norm(out)
    return out if out[0] >= 0 else -out


def rotation_between(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Smallest rotation taking direction ``a`` onto direction ``b`` (Rodrigues)."""
    a = a / np.linalg.norm(a)
    b = b / np.linalg.norm(b)
    v, c = np.cross(a, b), float(np.dot(a, b))
    if c < -1 + 1e-9:  # antiparallel: rotate pi around any axis orthogonal to a
        axis = np.cross(a, [1.0, 0.0, 0.0])
        if np.linalg.norm(axis) < 1e-6:
            axis = np.cross(a, [0.0, 1.0, 0.0])
        axis /= np.linalg.norm(axis)
        return np.asarray(2 * np.outer(axis, axis) - np.eye(3), dtype=np.float64)
    vx = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
    return np.asarray(np.eye(3) + vx + vx @ vx / (1 + c), dtype=np.float64)


def estimate_up(world_to_cam_rotations: np.ndarray) -> np.ndarray:
    """Gravity estimate from photo orientations: people hold cameras roughly level, so the mean of
    each camera's "up" axis (OpenCV/COLMAP camera y points down) approximates world up."""
    ups = -world_to_cam_rotations[:, 1, :]  # row 1 of R_cw is the camera y-axis in world coordinates
    up = ups.mean(axis=0)
    norm = np.linalg.norm(up)
    return np.asarray(up / norm, dtype=np.float64) if norm > 1e-6 else np.array([0.0, -1.0, 0.0])


@dataclass(frozen=True, slots=True)
class Similarity:
    """x' = scale * R (x - centre). Applied to points, Gaussian scales and orientations alike."""

    R: np.ndarray
    centre: np.ndarray
    scale: float

    @classmethod
    def to_viewer(cls, points: np.ndarray, up: np.ndarray, target_radius: float = VIEWER_RADIUS) -> Similarity:
        R = rotation_between(up, np.array([0.0, 1.0, 0.0]))
        centre = np.median(points, axis=0)
        radius = float(np.percentile(np.linalg.norm(points - centre, axis=1), 90)) or 1.0
        return cls(R=R, centre=centre, scale=target_radius / radius)

    def points(self, x: np.ndarray) -> np.ndarray:
        moved: np.ndarray = (x - self.centre) @ self.R.T * self.scale
        return moved.astype(np.float32)

    def quats(self, q_wxyz: np.ndarray) -> np.ndarray:
        return quat_multiply(matrix_to_quat(self.R)[None, :], q_wxyz)
