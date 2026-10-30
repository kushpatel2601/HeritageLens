"""Torch / transformers helpers. Nothing here imports torch at module import time, so the worker
core (and its tests) runs on machines without a deep-learning stack."""

from __future__ import annotations

import gc
import sys
from collections.abc import Mapping
from typing import Any


def resolve_device(preference: str) -> str:
    import torch

    if preference == "auto":
        return "cuda" if torch.cuda.is_available() else "cpu"
    if preference.startswith("cuda") and not torch.cuda.is_available():
        raise RuntimeError(f"device {preference!r} requested but CUDA is not available")
    return preference


def model_dtype(device: str) -> Any:
    """bf16 on Ampere and newer (A100 / L4 / H100); fp16 on Turing / Pascal (T4 / P100), which have
    no native bf16; fp32 on CPU."""
    import torch

    if not device.startswith("cuda"):
        return torch.float32
    major, _ = torch.cuda.get_device_capability(torch.device(device))
    return torch.bfloat16 if major >= 8 else torch.float16


def dtype_kwarg(dtype: Any) -> dict[str, Any]:
    """``from_pretrained`` renamed ``torch_dtype`` to ``dtype`` in transformers 4.56."""
    import transformers

    major, minor = (int(p) for p in transformers.__version__.split(".")[:2])
    return {"dtype": dtype} if (major, minor) >= (4, 56) else {"torch_dtype": dtype}


def to_device(batch: Mapping[str, Any], device: str, dtype: Any | None = None) -> dict[str, Any]:
    """Move a processor batch to ``device``; only floating tensors (pixels) are cast to ``dtype`` -
    token ids and grid sizes must stay integral."""
    out: dict[str, Any] = {}
    for key, value in batch.items():
        if hasattr(value, "to") and hasattr(value, "is_floating_point"):
            value = (
                value.to(device=device, dtype=dtype)
                if dtype is not None and value.is_floating_point()
                else value.to(device)
            )
        out[key] = value
    return out


def describe_device(preference: str) -> str:
    try:
        import torch
    except ImportError:
        return "cpu (no torch)"
    if preference != "cpu" and torch.cuda.is_available():
        props = torch.cuda.get_device_properties(0)
        return f"{props.name} ({props.total_memory / 2**30:.0f} GB, CUDA {torch.version.cuda})"
    return "cpu"


def free_accelerator_memory() -> None:
    gc.collect()
    torch = sys.modules.get("torch")
    if torch is not None and torch.cuda.is_available():
        torch.cuda.empty_cache()


def short_model_name(model_id: str, limit: int) -> str:
    return model_id.rstrip("/").rsplit("/", 1)[-1][:limit]
