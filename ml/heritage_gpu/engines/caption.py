"""Photo captioning with BLIP so unlabelled field photographs become text-searchable.

Captions only fill gaps: the server never overwrites a contributor- or curator-written caption.
"""

from __future__ import annotations

from typing import Any

from heritage_gpu.engines._torch import dtype_kwarg, model_dtype, resolve_device, short_model_name, to_device
from heritage_gpu.engines.base import Engine, JobIO, decode_image
from heritage_gpu.errors import JobError
from heritage_gpu.textproc import clean_caption

PROMPT = "a photograph of"  # conditional captioning: steers BLIP towards describing the subject


class BlipCaptioner(Engine):
    job_type = "caption"

    def __init__(self, model_id: str, device: str = "auto") -> None:
        super().__init__()
        self.model_id = model_id
        self.device_preference = device
        self._device = "cpu"
        self._dtype: Any = None
        self._processor: Any = None
        self._model: Any = None

    @property
    def name(self) -> str:
        return short_model_name(self.model_id, 40)

    def load(self) -> None:
        from transformers import BlipForConditionalGeneration, BlipProcessor

        self._device = resolve_device(self.device_preference)
        self._dtype = model_dtype(self._device)
        self._processor = BlipProcessor.from_pretrained(self.model_id)
        model = BlipForConditionalGeneration.from_pretrained(self.model_id, **dtype_kwarg(self._dtype))
        self._model = model.to(self._device).eval()

    def run(self, payload: dict[str, Any], io: JobIO) -> dict[str, Any]:
        import torch

        img = decode_image(io.fetch(payload["image_key"]), max_side=1024)
        batch = self._processor(images=img, text=PROMPT, return_tensors="pt")
        inputs = to_device(batch, self._device, self._dtype)
        with torch.inference_mode():
            out = self._model.generate(**inputs, num_beams=3, max_new_tokens=40, repetition_penalty=1.3)
        caption = clean_caption(str(self._processor.decode(out[0], skip_special_tokens=True)), PROMPT)
        if not caption:
            raise JobError("the captioner produced no text for this image", retryable=False)
        return {"engine": self.name, "caption": caption[:1000]}
