"""Engine registry: maps the worker configuration to one engine per job type.

Constructing engines is cheap - model weights load lazily on the first job (or ``--preload``).
"""

from __future__ import annotations

from heritage_gpu.config import WorkerConfig
from heritage_gpu.engines.base import Engine, JobIO, decode_image

__all__ = ["Engine", "JobIO", "build_engines", "decode_image"]


def _ocr(config: WorkerConfig) -> Engine:
    if config.ocr_engine == "vlm":
        from heritage_gpu.engines.ocr import VlmOCR

        return VlmOCR(config.ocr_model, config.device)
    if config.ocr_engine == "tesseract":
        from heritage_gpu.engines.ocr import TesseractOCR

        return TesseractOCR(config.ocr_default_langs)
    raise ValueError(f"unknown OCR engine {config.ocr_engine!r} (tesseract | vlm)")


def _translator(config: WorkerConfig) -> Engine:
    from heritage_gpu.engines.translate import AutoTranslator, IndicTrans2Translator, NllbTranslator

    indictrans = IndicTrans2Translator(config.indictrans_model, config.device, config.translate_batch_size)
    nllb = NllbTranslator(config.nllb_model, config.device, config.translate_batch_size)
    choices: dict[str, Engine] = {"indictrans2": indictrans, "nllb": nllb, "auto": AutoTranslator(indictrans, nllb)}
    if config.translator not in choices:
        raise ValueError(f"unknown translator {config.translator!r} (auto | indictrans2 | nllb)")
    return choices[config.translator]


def build_engines(config: WorkerConfig) -> dict[str, Engine]:
    """One engine per configured job type (``config.job_types``)."""
    if config.fake:
        from heritage_gpu.engines.fake import FAKE_ENGINES

        fakes = {cls.job_type: cls() for cls in FAKE_ENGINES}
        return {t: fakes[t] for t in config.job_types}

    engines: dict[str, Engine] = {}
    for job_type in config.job_types:
        if job_type == "ocr":
            engines[job_type] = _ocr(config)
        elif job_type == "translate":
            engines[job_type] = _translator(config)
        elif job_type == "caption":
            from heritage_gpu.engines.caption import BlipCaptioner

            engines[job_type] = BlipCaptioner(config.caption_model, config.device)
        elif job_type == "reconstruct3d":
            from heritage_gpu.engines.reconstruct import Reconstructor

            engines[job_type] = Reconstructor(
                config.depth_model,
                config.device,
                relief_max_points=config.relief_max_points,
                splat_steps=config.splat_steps,
                work_dir=config.work_dir,
            )
    return engines
