"""Multi-view digital twins: COLMAP structure-from-motion -> 3D Gaussian Splatting -> ``.splat``.

Pipeline (all on the Colab GPU worker):

1. ``pycolmap`` SIFT features, exhaustive matching and incremental mapping recover camera poses
   and a sparse point cloud from 8-60 overlapping photos. Images are then undistorted to pinhole
   cameras, which the rasteriser requires.
2. ``gsplat`` optimises one Gaussian per SfM point (densified / pruned by its ``DefaultStrategy``)
   against the photos with the standard 0.8 L1 + 0.2 (1 - SSIM) loss.
3. The result is moved into the viewer frame (y-up, centred, normalised scale - see
   :class:`heritage_gpu.geometry.Similarity`) and serialised as antimatter15 ``.splat``.

Heavy imports (``pycolmap``, ``torch``, ``gsplat``) happen inside the functions.
"""

from __future__ import annotations

import importlib.util
import math
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from heritage_gpu.engines.base import JobIO
from heritage_gpu.geometry import SH_C0, Similarity, estimate_up, write_splat

MIN_REGISTERED = 3
MAX_INIT_POINTS = 300_000
MAX_EXPORT_GAUSSIANS = 1_500_000
MIN_OPACITY = 0.005


class SfmError(Exception):
    """Structure-from-motion could not recover a usable reconstruction (too little overlap)."""


@dataclass(frozen=True, slots=True)
class MultiviewSupport:
    sfm: bool
    splat: bool


def multiview_support(device: str) -> MultiviewSupport:
    sfm = importlib.util.find_spec("pycolmap") is not None
    splat = device.startswith("cuda") and importlib.util.find_spec("gsplat") is not None
    return MultiviewSupport(sfm=sfm, splat=splat)


@dataclass(slots=True)
class View:
    name: str
    path: Path
    K: np.ndarray  # (3, 3) pinhole intrinsics
    world_to_cam: np.ndarray  # (4, 4)
    width: int
    height: int


@dataclass(slots=True)
class SfmScene:
    views: list[View]
    xyz: np.ndarray  # (N, 3) float64, COLMAP world frame
    rgb: np.ndarray  # (N, 3) uint8

    def rotations(self) -> np.ndarray:
        return np.stack([v.world_to_cam[:3, :3] for v in self.views])

    def camera_centres(self) -> np.ndarray:
        return np.stack([-v.world_to_cam[:3, :3].T @ v.world_to_cam[:3, 3] for v in self.views])

    def scene_scale(self) -> float:
        centres = self.camera_centres()
        spread = np.linalg.norm(centres - centres.mean(axis=0), axis=1)
        return float(np.max(spread) * 1.1) or 1.0

    def viewer_frame(self) -> Similarity:
        return Similarity.to_viewer(self.xyz, estimate_up(self.rotations()))

    def asset_ids(self) -> list[int]:
        ids = []
        for v in self.views:
            stem = Path(v.name).stem
            if stem.isdigit():
                ids.append(int(stem))
        return sorted(set(ids))


def _value(obj: Any, attr: str) -> Any:
    """pycolmap turned several properties into methods across 3.10 -> 3.12."""
    value = getattr(obj, attr)
    return value() if callable(value) else value


def _registered_ids(rec: Any) -> list[int]:
    if hasattr(rec, "reg_image_ids"):
        return sorted(_value(rec, "reg_image_ids"))
    return sorted(i for i, img in rec.images.items() if _value(img, "has_pose"))


def run_sfm(image_dir: Path, work: Path, progress: Callable[[str], None]) -> SfmScene:
    import pycolmap

    database, sparse, undistorted = work / "database.db", work / "sparse", work / "undistorted"
    sparse.mkdir(parents=True, exist_ok=True)
    pycolmap.extract_features(database_path=database, image_path=image_dir)
    pycolmap.match_exhaustive(database_path=database)
    progress("features extracted and matched")
    maps = pycolmap.incremental_mapping(database_path=database, image_path=image_dir, output_path=sparse)
    if not maps:
        raise SfmError("no photos could be registered")
    best = max(maps.values(), key=lambda r: r.num_reg_images())
    registered = best.num_reg_images()
    if registered < MIN_REGISTERED:
        raise SfmError(f"only {registered} photos registered (need {MIN_REGISTERED}+ with overlapping views)")
    progress(f"{registered} photos registered, {best.num_points3D()} sparse points")

    model_dir = sparse / "best"
    model_dir.mkdir(exist_ok=True)
    best.write(str(model_dir))
    pycolmap.undistort_images(output_path=undistorted, input_path=model_dir, image_path=image_dir)
    rec = pycolmap.Reconstruction(str(undistorted / "sparse"))

    views = []
    for image_id in _registered_ids(rec):
        image = rec.images[image_id]
        camera = rec.cameras[image.camera_id]
        world_to_cam = np.eye(4)
        world_to_cam[:3, :4] = np.asarray(_value(image, "cam_from_world").matrix())
        views.append(
            View(
                name=image.name,
                path=undistorted / "images" / image.name,
                K=np.asarray(camera.calibration_matrix(), dtype=np.float64),
                world_to_cam=world_to_cam,
                width=int(camera.width),
                height=int(camera.height),
            )
        )
    points = list(rec.points3D.values())
    if len(points) < 100:
        raise SfmError(f"only {len(points)} 3D points triangulated")
    xyz = np.array([p.xyz for p in points], dtype=np.float64)
    rgb = np.array([p.color for p in points], dtype=np.uint8)
    return SfmScene(views=views, xyz=xyz, rgb=rgb)


@dataclass(slots=True)
class Gaussians:
    means: np.ndarray  # (N, 3)
    scales: np.ndarray  # (N, 3) linear
    quats: np.ndarray  # (N, 4) w-first
    rgb: np.ndarray  # (N, 3) in [0, 1]
    alpha: np.ndarray  # (N,)

    def __len__(self) -> int:
        return int(self.means.shape[0])

    def to_splat(self, frame: Similarity) -> bytes:
        return write_splat(
            frame.points(self.means),
            (self.scales * frame.scale).astype(np.float32),
            frame.quats(self.quats),
            self.rgb,
            self.alpha,
        )


def ssim(x: Any, y: Any, window: int = 11, sigma: float = 1.5) -> Any:
    """Mean SSIM of two (B, C, H, W) tensors with a Gaussian window (no extra dependency)."""
    import torch
    import torch.nn.functional as F  # noqa: N812 - conventional PyTorch alias

    channels = x.shape[1]
    coords = torch.arange(window, dtype=x.dtype, device=x.device) - window // 2
    g = torch.exp(-(coords**2) / (2 * sigma**2))
    g = g / g.sum()
    kernel = (g[:, None] @ g[None, :]).expand(channels, 1, window, window).contiguous()

    def blur(t: Any) -> Any:
        return F.conv2d(t, kernel, padding=window // 2, groups=channels)

    mu_x, mu_y = blur(x), blur(y)
    var_x = blur(x * x) - mu_x**2
    var_y = blur(y * y) - mu_y**2
    cov = blur(x * y) - mu_x * mu_y
    c1, c2 = 0.01**2, 0.03**2
    num = (2 * mu_x * mu_y + c1) * (2 * cov + c2)
    den = (mu_x**2 + mu_y**2 + c1) * (var_x + var_y + c2)
    return (num / den).mean()


def _knn_mean_distance(points: Any, k: int = 3, chunk: int = 1024) -> Any:
    import torch

    out = []
    kk = min(k + 1, points.shape[0])
    for start in range(0, points.shape[0], chunk):
        d = torch.cdist(points[start : start + chunk], points)
        out.append(d.topk(kk, largest=False).values[:, 1:].mean(dim=1))
    return torch.cat(out)


def train_gaussians(
    scene: SfmScene, *, steps: int, device: str, io: JobIO, max_side: int = 1280, seed: int = 0
) -> Gaussians:
    import torch
    import torch.nn.functional as F  # noqa: N812 - conventional PyTorch alias
    from gsplat import rasterization
    from gsplat.strategy import DefaultStrategy

    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)
    dev = torch.device(device)

    cameras = []
    for view in scene.views:
        img = Image.open(view.path).convert("RGB")
        s = min(1.0, max_side / max(img.size))
        if s < 1.0:
            img = img.resize((round(img.width * s), round(img.height * s)), Image.Resampling.LANCZOS)
        K = view.K.copy()
        K[0] *= img.width / view.width
        K[1] *= img.height / view.height
        cameras.append(
            (
                torch.from_numpy(np.asarray(img, dtype=np.float32) / 255.0).to(dev),
                torch.tensor(K, dtype=torch.float32, device=dev),
                torch.tensor(view.world_to_cam, dtype=torch.float32, device=dev),
            )
        )

    xyz, rgb = scene.xyz, scene.rgb
    if len(xyz) > MAX_INIT_POINTS:
        keep = rng.choice(len(xyz), MAX_INIT_POINTS, replace=False)
        xyz, rgb = xyz[keep], rgb[keep]
    points = torch.tensor(xyz, dtype=torch.float32, device=dev)
    colours = torch.tensor(rgb, dtype=torch.float32, device=dev) / 255.0
    n = points.shape[0]
    scene_scale = scene.scene_scale()

    params = torch.nn.ParameterDict(
        {
            "means": torch.nn.Parameter(points),
            "scales": torch.nn.Parameter(torch.log(_knn_mean_distance(points).clamp_min(1e-6))[:, None].repeat(1, 3)),
            "quats": torch.nn.Parameter(F.normalize(torch.randn(n, 4, device=dev), dim=-1)),
            "opacities": torch.nn.Parameter(torch.logit(torch.full((n,), 0.1, device=dev))),
            "sh0": torch.nn.Parameter(((colours - 0.5) / SH_C0)[:, None, :]),
        }
    )
    learning_rates = {"means": 1.6e-4 * scene_scale, "scales": 5e-3, "quats": 1e-3, "opacities": 5e-2, "sh0": 2.5e-3}
    optimizers = {
        name: torch.optim.Adam([{"params": params[name], "lr": lr, "name": name}], eps=1e-15)
        for name, lr in learning_rates.items()
    }
    scheduler = torch.optim.lr_scheduler.ExponentialLR(optimizers["means"], gamma=0.01 ** (1.0 / steps))
    strategy = DefaultStrategy(
        refine_start_iter=500, refine_stop_iter=int(steps * 0.6), refine_every=100, reset_every=3000, verbose=False
    )
    strategy.check_sanity(params, optimizers)
    state = strategy.initialize_state(scene_scale=scene_scale)

    loss_ema = math.nan
    for step in range(steps):
        image, K, view_matrix = cameras[int(rng.integers(len(cameras)))]
        height, width = image.shape[:2]
        renders, _alphas, info = rasterization(
            means=params["means"],
            quats=params["quats"],
            scales=torch.exp(params["scales"]),
            opacities=torch.sigmoid(params["opacities"]),
            colors=params["sh0"],
            viewmats=view_matrix[None],
            Ks=K[None],
            width=width,
            height=height,
            sh_degree=0,
            packed=False,
        )
        strategy.step_pre_backward(params, optimizers, state, step, info)
        pred = renders[0]
        l1 = (pred - image).abs().mean()
        structural = ssim(pred.permute(2, 0, 1)[None], image.permute(2, 0, 1)[None])
        loss = 0.8 * l1 + 0.2 * (1.0 - structural)
        loss.backward()
        for optimizer in optimizers.values():
            optimizer.step()
            optimizer.zero_grad(set_to_none=True)
        scheduler.step()
        strategy.step_post_backward(params, optimizers, state, step, info, packed=False)

        value = float(loss.detach())
        loss_ema = value if math.isnan(loss_ema) else 0.98 * loss_ema + 0.02 * value
        if step % 100 == 0:
            io.check_cancelled()
        if step % 1000 == 0 or step == steps - 1:
            io.progress(f"splat step {step + 1}/{steps}: loss {loss_ema:.4f}, {params['means'].shape[0]:,} gaussians")

    with torch.no_grad():
        alpha = torch.sigmoid(params["opacities"])
        order = torch.argsort(alpha, descending=True)
        order = order[alpha[order] > MIN_OPACITY][:MAX_EXPORT_GAUSSIANS]
        return Gaussians(
            means=params["means"][order].cpu().numpy().astype(np.float64),
            scales=torch.exp(params["scales"][order]).cpu().numpy().astype(np.float64),
            quats=F.normalize(params["quats"][order], dim=-1).cpu().numpy().astype(np.float64),
            rgb=(0.5 + SH_C0 * params["sh0"][order, 0, :]).clamp(0.0, 1.0).cpu().numpy().astype(np.float64),
            alpha=alpha[order].cpu().numpy().astype(np.float64),
        )
