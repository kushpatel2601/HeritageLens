"""Digital twins for heritage sites from archive photographs.

* ``depth-relief`` (any number of photos, uses the first): Depth-Anything-V2 monocular depth lifted
  into a coloured point-cloud relief - works even for a single historic photograph.
* ``gaussian-splat`` (8+ overlapping photos): COLMAP SfM + gsplat training, see ``multiview``.
  Degrades gracefully: without CUDA/gsplat it exports the SfM sparse cloud (``sfm-points``); when
  the photos do not overlap enough for SfM it falls back to a depth relief.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from heritage_gpu.engines._torch import resolve_device, short_model_name
from heritage_gpu.engines.base import Engine, JobIO, decode_image
from heritage_gpu.engines.multiview import SfmError, multiview_support, run_sfm, train_gaussians
from heritage_gpu.errors import JobError
from heritage_gpu.geometry import PointCloud, relief_from_disparity, write_ply

log = logging.getLogger(__name__)


class Reconstructor(Engine):
    job_type = "reconstruct3d"

    def __init__(
        self,
        depth_model: str,
        device: str = "auto",
        *,
        relief_max_points: int = 600_000,
        splat_steps: int = 7000,
        work_dir: Path = Path("outputs"),
    ) -> None:
        super().__init__()
        self.depth_model = depth_model
        self.device_preference = device
        self.relief_max_points = relief_max_points
        self.splat_steps = splat_steps
        self.work_dir = work_dir
        self._device = "cpu"
        self._pipe: Any = None

    @property
    def name(self) -> str:
        return short_model_name(self.depth_model, 60)

    def load(self) -> None:
        from transformers import pipeline

        self._device = resolve_device(self.device_preference)
        self._pipe = pipeline("depth-estimation", model=self.depth_model, device=self._device)
        support = multiview_support(self._device)
        log.info(
            "depth model %s on %s; multi-view: sfm=%s splat=%s", self.name, self._device, support.sfm, support.splat
        )

    # ------------------------------------------------------------------ monocular relief
    def disparity(self, img: Image.Image) -> np.ndarray:
        import torch

        pred = torch.as_tensor(self._pipe(img)["predicted_depth"]).float().cpu()
        while pred.dim() < 4:
            pred = pred.unsqueeze(0)
        if tuple(pred.shape[-2:]) != (img.height, img.width):
            pred = torch.nn.functional.interpolate(
                pred, size=(img.height, img.width), mode="bicubic", align_corners=False
            )
        return np.asarray(pred[0, 0].numpy(), dtype=np.float32)

    def _relief(self, payload: dict[str, Any], io: JobIO) -> dict[str, Any]:
        first = payload["images"][0]
        img = decode_image(io.fetch(first["image_key"]), max_side=1536)
        io.check_cancelled()
        try:
            cloud = relief_from_disparity(np.asarray(img), self.disparity(img), max_points=self.relief_max_points)
        except ValueError as exc:
            raise JobError(f"cannot build a relief from this photo: {exc}", retryable=False) from exc
        data = write_ply(cloud, f"HeritageLens depth relief ({self.name})")
        artifact = io.upload_artifact(f"relief-{first['asset_id']}.ply", data)
        io.progress(f"relief: {len(cloud):,} points, {len(data) / 2**20:.1f} MB")
        return {
            "artifact_key": artifact["key"],
            "format": "ply",
            "method": "depth-relief",
            "point_count": len(cloud),
            "title": payload.get("title"),
            "source_asset_ids": [int(first["asset_id"])],
        }

    # ------------------------------------------------------------------ multi-view
    def _multiview(self, payload: dict[str, Any], io: JobIO) -> dict[str, Any]:
        support = multiview_support(self._device)
        if not support.sfm:
            io.progress("pycolmap is not installed - falling back to a depth relief")
            return self._relief(payload, io)
        work = self.work_dir / f"job-{io.job_id}"
        shutil.rmtree(work, ignore_errors=True)
        image_dir = work / "images"
        image_dir.mkdir(parents=True)
        try:
            for item in payload["images"]:
                io.check_cancelled()
                img = decode_image(io.fetch(item["image_key"]), max_side=1600)
                img.save(image_dir / f"{int(item['asset_id'])}.jpg", quality=95)
            try:
                scene = run_sfm(image_dir, work, io.progress)
            except SfmError as exc:
                io.progress(f"structure-from-motion failed ({exc}) - falling back to a depth relief")
                return self._relief(payload, io)
            io.check_cancelled()
            frame = scene.viewer_frame()
            if support.splat:
                gaussians = train_gaussians(scene, steps=self.splat_steps, device=self._device, io=io)
                artifact = io.upload_artifact("scene.splat", gaussians.to_splat(frame))
                method, fmt, count = "gaussian-splat", "splat", len(gaussians)
            else:
                io.progress("gsplat / CUDA unavailable - exporting the sparse SfM point cloud")
                cloud = PointCloud(xyz=frame.points(scene.xyz), rgb=scene.rgb)
                artifact = io.upload_artifact("sparse.ply", write_ply(cloud, "HeritageLens SfM sparse cloud"))
                method, fmt, count = "sfm-points", "ply", len(cloud)
        finally:
            shutil.rmtree(work, ignore_errors=True)
        return {
            "artifact_key": artifact["key"],
            "format": fmt,
            "method": method,
            "point_count": count,
            "title": payload.get("title"),
            "source_asset_ids": scene.asset_ids(),
        }

    def run(self, payload: dict[str, Any], io: JobIO) -> dict[str, Any]:
        if not payload.get("images"):
            raise JobError("no photos in the reconstruction request", retryable=False)
        if payload.get("method") == "gaussian-splat":
            return self._multiview(payload, io)
        return self._relief(payload, io)
