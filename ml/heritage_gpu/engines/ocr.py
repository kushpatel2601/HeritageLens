"""OCR engines for scanned manuscripts, letters and survey sheets.

* :class:`TesseractOCR` (default) - Tesseract 5 LSTM models for 12 Indic scripts + English. One
  ``image_to_data`` pass yields both text and word confidences. Without a language hint the script
  is detected with Tesseract OSD so a Gujarati letter is not read with the Devanagari model.
* :class:`VlmOCR` (opt-in) - a vision-language model (Qwen2.5-VL by default) that transcribes
  degraded or handwritten pages Tesseract struggles with. Needs ~8 GB VRAM in fp16.
"""

from __future__ import annotations

import logging
from typing import Any

from PIL import Image, ImageOps

from heritage_gpu.engines._torch import dtype_kwarg, model_dtype, resolve_device, short_model_name, to_device
from heritage_gpu.engines.base import Engine, JobIO, decode_image
from heritage_gpu.langs import NAMES, langs_for_script, tesseract_langs
from heritage_gpu.textproc import assemble_tesseract, normalize

log = logging.getLogger(__name__)

MAX_PAGE_TEXT = 200_000  # server-side OcrPageResult limit


def prepare_page(img: Image.Image) -> Image.Image:
    """Grayscale, upscale small scans (Tesseract wants ~30 px x-height) and stretch contrast for
    faded ink. Deliberately no binarisation: the LSTM models do better on grayscale."""
    gray = ImageOps.grayscale(img)
    if min(gray.size) < 1000:
        gray = gray.resize((gray.width * 2, gray.height * 2), Image.Resampling.LANCZOS)
    return ImageOps.autocontrast(gray, cutoff=1)


class TesseractOCR(Engine):
    job_type = "ocr"

    def __init__(self, default_langs: str = "guj+hin+eng") -> None:
        super().__init__()
        self.default_langs = default_langs
        self._version = "5"
        self._available: set[str] = set()
        self._tess: Any = None

    @property
    def name(self) -> str:
        return f"tesseract-{self._version}"

    def load(self) -> None:
        try:
            import pytesseract
        except ImportError as exc:
            raise RuntimeError("pytesseract is not installed (pip install 'heritage-gpu[models]')") from exc
        try:
            self._version = str(pytesseract.get_tesseract_version()).split()[0]
        except pytesseract.TesseractNotFoundError as exc:
            raise RuntimeError("the tesseract binary is not installed (apt-get install tesseract-ocr)") from exc
        self._tess = pytesseract
        self._available = set(pytesseract.get_languages(config=""))
        log.info("tesseract %s, language models: %s", self._version, " ".join(sorted(self._available)))

    def _langs_for(self, img: Image.Image, hint: str | None) -> str:
        if hint and hint != "en":
            return tesseract_langs(hint, self._available, self.default_langs)
        if "osd" in self._available:
            try:
                osd = self._tess.image_to_osd(img, output_type=self._tess.Output.DICT)
                picked = langs_for_script(osd.get("script"), self._available)
                if picked:
                    return picked
            except Exception as exc:  # OSD needs enough text to decide; fall back quietly
                log.debug("script detection failed: %s", exc)
        return tesseract_langs(hint, self._available, self.default_langs)

    def run(self, payload: dict[str, Any], io: JobIO) -> dict[str, Any]:
        hint = payload.get("lang_hint")
        pages = []
        for page in payload["pages"]:
            io.check_cancelled()
            img = prepare_page(decode_image(io.fetch(page["image_key"]), max_side=5000))
            langs = self._langs_for(img, hint)
            data = self._tess.image_to_data(img, lang=langs, config="--psm 3", output_type=self._tess.Output.DICT)
            text, confidence = assemble_tesseract(data)
            pages.append({"page_no": int(page["page_no"]), "text": text[:MAX_PAGE_TEXT], "confidence": confidence})
            io.progress(f"page {page['page_no']} [{langs}]: {len(text)} chars, confidence {confidence}")
        return {"engine": self.name, "pages": pages}


VLM_PROMPT = (
    "Transcribe all text on this archival page exactly as written, in its original script. "
    "Preserve line breaks. Do not translate, summarise or add commentary; output only the transcription."
)


class VlmOCR(Engine):
    job_type = "ocr"

    def __init__(self, model_id: str, device: str = "auto", max_new_tokens: int = 2048) -> None:
        super().__init__()
        self.model_id = model_id
        self.device_preference = device
        self.max_new_tokens = max_new_tokens
        self._device = "cpu"
        self._dtype: Any = None
        self._processor: Any = None
        self._model: Any = None

    @property
    def name(self) -> str:
        return f"vlm-{short_model_name(self.model_id, 50)}"

    def load(self) -> None:
        from transformers import AutoModelForImageTextToText, AutoProcessor

        self._device = resolve_device(self.device_preference)
        self._dtype = model_dtype(self._device)
        self._processor = AutoProcessor.from_pretrained(self.model_id)
        model = AutoModelForImageTextToText.from_pretrained(self.model_id, **dtype_kwarg(self._dtype))
        self._model = model.to(self._device).eval()

    def _transcribe(self, img: Image.Image, prompt: str) -> str:
        import torch

        messages = [{"role": "user", "content": [{"type": "image"}, {"type": "text", "text": prompt}]}]
        chat = self._processor.apply_chat_template(messages, add_generation_prompt=True, tokenize=False)
        batch = self._processor(text=[chat], images=[img], return_tensors="pt")
        inputs = to_device(batch, self._device, self._dtype)
        with torch.inference_mode():
            out = self._model.generate(
                **inputs, max_new_tokens=self.max_new_tokens, do_sample=False, repetition_penalty=1.05
            )
        new_tokens = out[:, inputs["input_ids"].shape[1] :]
        return str(self._processor.batch_decode(new_tokens, skip_special_tokens=True)[0])

    def run(self, payload: dict[str, Any], io: JobIO) -> dict[str, Any]:
        language = NAMES.get(payload.get("lang_hint") or "")
        prompt = VLM_PROMPT + (f" The page is most likely written in {language}." if language else "")
        pages = []
        for page in payload["pages"]:
            io.check_cancelled()
            img = decode_image(io.fetch(page["image_key"]), max_side=1600)
            text = normalize(self._transcribe(img, prompt))
            pages.append({"page_no": int(page["page_no"]), "text": text[:MAX_PAGE_TEXT], "confidence": None})
            io.progress(f"page {page['page_no']}: {len(text)} chars")
        return {"engine": self.name[:60], "pages": pages}
