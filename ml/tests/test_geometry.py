from __future__ import annotations

import math

import numpy as np
import pytest

from heritage_gpu.geometry import (
    SPLAT_DTYPE,
    VIEWER_RADIUS,
    PointCloud,
    Similarity,
    estimate_up,
    matrix_to_quat,
    quat_multiply,
    quat_to_matrix,
    relief_from_disparity,
    rotation_between,
    write_ply,
    write_splat,
)

RNG = np.random.default_rng(7)


def _random_quats(n: int) -> np.ndarray:
    q = RNG.normal(size=(n, 4))
    return q / np.linalg.norm(q, axis=1, keepdims=True)


def _is_rotation(R: np.ndarray) -> bool:
    return bool(np.allclose(R @ R.T, np.eye(3), atol=1e-9) and math.isclose(np.linalg.det(R), 1.0, abs_tol=1e-9))


# ---------------------------------------------------------------- serialisation
def test_write_ply_is_binary_little_endian_and_round_trips() -> None:
    xyz = RNG.normal(size=(50, 3)).astype(np.float32)
    rgb = RNG.integers(0, 256, size=(50, 3), dtype=np.uint8)
    data = write_ply(PointCloud(xyz, rgb), comment="multi\nline comment")

    header, _, body = data.partition(b"end_header\n")
    lines = header.decode("ascii").splitlines()
    assert lines[:2] == ["ply", "format binary_little_endian 1.0"]
    assert "comment multi line comment" in lines  # newlines in comments would corrupt the header
    assert "element vertex 50" in lines
    assert len(body) == 50 * 15

    rec = np.frombuffer(body, dtype=[("xyz", "<f4", 3), ("rgb", "u1", 3)])
    np.testing.assert_array_equal(rec["xyz"], xyz)
    np.testing.assert_array_equal(rec["rgb"], rgb)


def test_point_cloud_rejects_mismatched_shapes() -> None:
    with pytest.raises(ValueError):
        PointCloud(np.zeros((4, 3), np.float32), np.zeros((3, 3), np.uint8))
    with pytest.raises(ValueError):
        PointCloud(np.zeros((4, 2), np.float32), np.zeros((4, 2), np.uint8))


def test_write_splat_layout_ordering_and_encoding() -> None:
    means = np.array([[0, 0, 0], [1, 1, 1], [2, 2, 2]], dtype=np.float32)
    scales = np.array([[0.1] * 3, [0.5] * 3, [0.2] * 3], dtype=np.float32)
    quats = np.array([[2.0, 0, 0, 0], [1, 0, 0, 0], [0, 0, 0, -1]])  # unnormalised on purpose
    rgb = np.array([[1.0, 0, 0], [0, 1.0, 0], [0, 0, 1.0]])
    alpha = np.array([1.0, 0.5, 1.0])

    data = write_splat(means, scales, quats, rgb, alpha)
    assert len(data) == 3 * 32
    rec = np.frombuffer(data, dtype=SPLAT_DTYPE)
    # Sorted by volume x opacity, descending: 0.125*0.5 > 0.008*1 > 0.001*1.
    np.testing.assert_array_equal(rec["pos"][:, 0], [1, 2, 0])
    np.testing.assert_allclose(rec["scale"][0], [0.5] * 3)
    np.testing.assert_array_equal(rec["rgba"][0], [0, 255, 0, 128])
    np.testing.assert_array_equal(rec["rot"][2], [255, 128, 128, 128])  # (2,0,0,0) normalised to identity
    np.testing.assert_array_equal(rec["rot"][1], [128, 128, 128, 0])


def test_write_splat_rejects_inconsistent_shapes() -> None:
    z = np.zeros((2, 3))
    with pytest.raises(ValueError):
        write_splat(z, z, np.zeros((3, 4)), z, np.zeros(2))


# ---------------------------------------------------------------- monocular relief
def _ramp(h: int = 120, w: int = 160) -> tuple[np.ndarray, np.ndarray]:
    rgb = RNG.integers(0, 256, size=(h, w, 3), dtype=np.uint8)
    disparity = np.tile(np.linspace(0.2, 1.0, w, dtype=np.float32), (h, 1))  # right side nearest
    return rgb, disparity


def test_relief_is_centred_scaled_and_depth_ordered() -> None:
    rgb, disparity = _ramp()
    cloud = relief_from_disparity(rgb, disparity)
    assert cloud.xyz.dtype == np.float32 and cloud.rgb.dtype == np.uint8
    assert len(cloud) > 0.9 * rgb.shape[0] * rgb.shape[1]  # smooth ramp: almost nothing filtered
    np.testing.assert_allclose(cloud.xyz.mean(axis=0), 0, atol=1e-3)
    radius = np.percentile(np.linalg.norm(cloud.xyz, axis=1), 98)
    assert radius == pytest.approx(VIEWER_RADIUS, rel=1e-3)
    right = cloud.xyz[:, 0] > 0
    assert cloud.xyz[right, 2].mean() > cloud.xyz[~right, 2].mean()  # nearer = larger z (camera looks down -z)


def test_relief_respects_point_budget_and_drops_background_and_edges() -> None:
    rgb, disparity = _ramp(200, 300)
    assert len(relief_from_disparity(rgb, disparity, max_points=5_000)) <= 5_000

    stepped = disparity.copy()
    stepped[:, :20] = 0.0  # "sky": farther than the 1st percentile -> dropped by min_disparity
    stepped[:, 150:] += 5.0  # a depth discontinuity -> flying pixels along it are removed
    cloud = relief_from_disparity(rgb, stepped)
    assert len(cloud) < 200 * 300 - 200 * 20


@pytest.mark.parametrize(
    ("rgb_shape", "disp_shape"),
    [((10, 10, 3), (10, 11)), ((10, 10), (10, 10)), ((10, 10, 4), (10, 10))],
)
def test_relief_validates_shapes(rgb_shape: tuple[int, ...], disp_shape: tuple[int, ...]) -> None:
    with pytest.raises(ValueError, match="do not match"):
        relief_from_disparity(np.zeros(rgb_shape, np.uint8), np.zeros(disp_shape, np.float32))


def test_relief_refuses_flat_depth() -> None:
    with pytest.raises(ValueError, match="flat"):
        relief_from_disparity(np.zeros((32, 32, 3), np.uint8), np.ones((32, 32), np.float32))


# ---------------------------------------------------------------- rotations
def test_quaternion_matrix_round_trip_and_product() -> None:
    for q in _random_quats(200):
        R = quat_to_matrix(q)
        assert _is_rotation(R)
        back = matrix_to_quat(R)
        assert back[0] >= 0
        np.testing.assert_allclose(back, q if q[0] >= 0 else -q, atol=1e-9)

    a, b = _random_quats(2)
    np.testing.assert_allclose(quat_to_matrix(quat_multiply(a, b)), quat_to_matrix(a) @ quat_to_matrix(b), atol=1e-9)
    batch = quat_multiply(np.tile(a, (5, 1)), _random_quats(5))
    assert batch.shape == (5, 4)


def test_matrix_to_quat_handles_every_branch() -> None:
    for axis in np.eye(3):  # 180 degree turns have trace -1 and exercise the diagonal branches
        R = 2 * np.outer(axis, axis) - np.eye(3)
        np.testing.assert_allclose(quat_to_matrix(matrix_to_quat(R)), R, atol=1e-9)


@pytest.mark.parametrize("case", ["random", "parallel", "antiparallel", "antiparallel-x"])
def test_rotation_between_maps_a_onto_b(case: str) -> None:
    a = RNG.normal(size=3)
    b = {"random": RNG.normal(size=3), "parallel": 3 * a, "antiparallel": -a, "antiparallel-x": None}[case]
    if case == "antiparallel-x":
        a, b = np.array([2.0, 0, 0]), np.array([-1.0, 0, 0])
    assert b is not None
    R = rotation_between(a, b)
    assert _is_rotation(R)
    np.testing.assert_allclose(R @ (a / np.linalg.norm(a)), b / np.linalg.norm(b), atol=1e-9)


def _yaw_cameras(world_up: np.ndarray, n: int = 8, tilt: float = 0.1) -> np.ndarray:
    """World-to-camera rotations of level-ish cameras orbiting ``world_up`` (OpenCV: y down, z forward)."""
    up = world_up / np.linalg.norm(world_up)
    helper = np.array([1.0, 0, 0]) if abs(up[0]) < 0.9 else np.array([0, 1.0, 0])
    e1 = np.cross(up, helper)
    e1 /= np.linalg.norm(e1)
    e2 = np.cross(up, e1)
    rots = []
    for k in range(n):
        t = 2 * math.pi * k / n
        forward = math.cos(t) * e1 + math.sin(t) * e2 + tilt * up * (-1) ** k
        forward /= np.linalg.norm(forward)
        down = -up - np.dot(-up, forward) * forward
        down /= np.linalg.norm(down)
        right = np.cross(down, forward)
        rots.append(np.stack([right, down, forward]))  # rows: camera axes in world coordinates
    return np.stack(rots)


def test_estimate_up_recovers_gravity_from_camera_poses() -> None:
    world_up = np.array([0.3, -0.2, 1.0])
    rots = _yaw_cameras(world_up)
    assert all(_is_rotation(R) for R in rots)
    up = estimate_up(rots)
    np.testing.assert_allclose(up, world_up / np.linalg.norm(world_up), atol=1e-6)
    # Degenerate input (ups cancel out) falls back to the OpenCV default.
    np.testing.assert_allclose(estimate_up(np.stack([np.eye(3), np.diag([1.0, -1.0, -1.0])])), [0, -1, 0])


def test_similarity_moves_scene_into_viewer_frame_consistently() -> None:
    world_up = np.array([0.0, 0.0, 1.0])
    pts = RNG.normal(size=(500, 3)) * [4.0, 4.0, 1.0] + [10.0, -3.0, 2.0]
    sim = Similarity.to_viewer(pts, world_up)

    moved = sim.points(pts)
    assert moved.dtype == np.float32
    np.testing.assert_allclose(np.median(moved, axis=0), 0, atol=1e-4)
    assert np.percentile(np.linalg.norm(moved, axis=1), 90) == pytest.approx(VIEWER_RADIUS, rel=1e-4)
    lifted = sim.points((np.median(pts, axis=0) + world_up)[None, :])[0]
    np.testing.assert_allclose(lifted / np.linalg.norm(lifted), [0, 1, 0], atol=1e-6)  # world up -> viewer +y

    q = _random_quats(4)
    rotated = sim.quats(q)
    for before, after in zip(q, rotated, strict=True):
        np.testing.assert_allclose(quat_to_matrix(after), sim.R @ quat_to_matrix(before), atol=1e-9)
