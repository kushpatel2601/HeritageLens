"""Indic -> English translation of archive text chunks.

* :class:`IndicTrans2Translator` - AI4Bharat IndicTrans2 (distilled 200M by default), the strongest
  open model for the 22 scheduled Indian languages; needs ``IndicTransToolkit`` for its
  script-aware pre/post-processing.
* :class:`NllbTranslator` - Meta NLLB-200 (distilled 600M); no extra dependencies.
* :class:`AutoTranslator` - IndicTrans2 when it loads, otherwise NLLB, so a missing toolkit or a
  gated checkpoint degrades quality instead of stopping the worker.

All of them translate sentence by sentence in length-sorted batches (``translate_documents``) so a
long journal entry is never silently truncated at the model's maximum input length.
"""

from __future__ import annotations

import logging
from abc import abstractmethod
from collections import defaultdict
from typing import Any

from heritage_gpu.engines._torch import dtype_kwarg, model_dtype, resolve_device, short_model_name
from heritage_gpu.engines.base import Engine, JobIO
from heritage_gpu.langs import FLORES, NAMES
from heritage_gpu.textproc import normalize, translate_documents

log = logging.getLogger(__name__)

TARGET = "eng_Latn"
MAX_TRANSLATION = 20_000  # server-side TranslationItem limit


class SentenceTranslator(Engine):
    """Shared job handling: group chunks by language, translate, map back to chunk ids."""

    job_type = "translate"

    def __init__(self, batch_size: int = 16) -> None:
        super().__init__()
        self.batch_size = batch_size

    def supports(self, lang: str) -> bool:
        return lang in FLORES and lang != "en"

    @abstractmethod
    def translate_batch(self, sentences: list[str], lang: str) -> list[str]:
        """Translate one batch of sentences written in ``lang`` (ISO 639-1) into English."""

    def run(self, payload: dict[str, Any], io: JobIO) -> dict[str, Any]:
        groups: dict[str, list[tuple[int, str]]] = defaultdict(list)
        skipped = 0
        for item in payload["items"]:
            lang = item.get("lang") or payload.get("src_lang") or ""
            text = normalize(item.get("text") or "")
            if text and self.supports(lang):
                groups[lang].append((int(item["chunk_id"]), text))
            else:
                skipped += 1
        items: list[dict[str, Any]] = []
        for lang, group in groups.items():

            def batch(sentences: list[str], lang: str = lang) -> list[str]:
                io.check_cancelled()
                return self.translate_batch(sentences, lang)

            outputs = translate_documents([text for _, text in group], batch, batch_size=self.batch_size)
            items += [
                {"chunk_id": chunk_id, "translation": out[:MAX_TRANSLATION]}
                for (chunk_id, _), out in zip(group, outputs, strict=True)
                if out
            ]
            io.progress(f"{NAMES.get(lang, lang)}: {len(group)} chunks translated")
        if skipped:
            io.progress(f"skipped {skipped} empty or unsupported chunks")
        return {"engine": self.name[:80], "items": items}


class NllbTranslator(SentenceTranslator):
    def __init__(self, model_id: str, device: str = "auto", batch_size: int = 16) -> None:
        super().__init__(batch_size)
        self.model_id = model_id
        self.device_preference = device
        self._device = "cpu"
        self._tokenizer: Any = None
        self._model: Any = None

    @property
    def name(self) -> str:
        return short_model_name(self.model_id, 80)

    def load(self) -> None:
        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

        self._device = resolve_device(self.device_preference)
        self._tokenizer = AutoTokenizer.from_pretrained(self.model_id)
        model = AutoModelForSeq2SeqLM.from_pretrained(self.model_id, **dtype_kwarg(model_dtype(self._device)))
        self._model = model.to(self._device).eval()

    def translate_batch(self, sentences: list[str], lang: str) -> list[str]:
        import torch

        tok = self._tokenizer
        tok.src_lang = FLORES[lang]
        enc = tok(sentences, return_tensors="pt", padding=True, truncation=True, max_length=256).to(self._device)
        with torch.inference_mode():
            out = self._model.generate(
                **enc, forced_bos_token_id=tok.convert_tokens_to_ids(TARGET), num_beams=4, max_new_tokens=256
            )
        return [str(s) for s in tok.batch_decode(out, skip_special_tokens=True)]


class IndicTrans2Translator(SentenceTranslator):
    def __init__(self, model_id: str, device: str = "auto", batch_size: int = 16) -> None:
        super().__init__(batch_size)
        self.model_id = model_id
        self.device_preference = device
        self._device = "cpu"
        self._processor: Any = None
        self._tokenizer: Any = None
        self._model: Any = None
        self._use_cache = True

    @property
    def name(self) -> str:
        return short_model_name(self.model_id, 80)

    def load(self) -> None:
        try:
            from IndicTransToolkit.processor import IndicProcessor
        except ImportError:
            from IndicTransToolkit import IndicProcessor  # older toolkit layout
        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

        self._device = resolve_device(self.device_preference)
        self._processor = IndicProcessor(inference=True)
        self._tokenizer = AutoTokenizer.from_pretrained(self.model_id, trust_remote_code=True)
        model = AutoModelForSeq2SeqLM.from_pretrained(
            self.model_id, trust_remote_code=True, **dtype_kwarg(model_dtype(self._device))
        )
        self._model = model.to(self._device).eval()

    def _generate(self, enc: Any) -> Any:
        import torch

        kwargs = {"min_length": 0, "max_length": 256, "num_beams": 5, "num_return_sequences": 1}
        with torch.inference_mode():
            try:
                return self._model.generate(**enc, use_cache=self._use_cache, **kwargs)
            except (AttributeError, TypeError) as exc:
                # IndicTrans2's remote modelling code predates the transformers Cache API; newer
                # releases fail inside the KV cache. Generation without it is slower but correct.
                if not self._use_cache:
                    raise
                log.warning("IndicTrans2 generation with KV cache failed (%s); retrying without it", exc)
                self._use_cache = False
                return self._model.generate(**enc, use_cache=False, **kwargs)

    def translate_batch(self, sentences: list[str], lang: str) -> list[str]:
        batch = self._processor.preprocess_batch(sentences, src_lang=FLORES[lang], tgt_lang=TARGET)
        enc = self._tokenizer(
            batch, truncation=True, padding="longest", return_tensors="pt", return_attention_mask=True
        ).to(self._device)
        out = self._generate(enc)
        decoded = self._tokenizer.batch_decode(out, skip_special_tokens=True, clean_up_tokenization_spaces=True)
        return [str(s) for s in self._processor.postprocess_batch(decoded, lang=TARGET)]


class AutoTranslator(Engine):
    job_type = "translate"

    def __init__(self, primary: SentenceTranslator, fallback: SentenceTranslator) -> None:
        super().__init__()
        self.primary = primary
        self.fallback = fallback
        self.active: SentenceTranslator | None = None

    @property
    def name(self) -> str:
        return self.active.name if self.active else f"{self.primary.name}|{self.fallback.name}"

    def load(self) -> None:
        try:
            self.primary.ensure_loaded()
            self.active = self.primary
        except Exception as exc:
            log.warning("%s unavailable (%s); falling back to %s", self.primary.name, exc, self.fallback.name)
            self.fallback.ensure_loaded()
            self.active = self.fallback
        log.info("translator: %s", self.active.name)

    def run(self, payload: dict[str, Any], io: JobIO) -> dict[str, Any]:
        assert self.active is not None, "ensure_loaded() first"
        return self.active.run(payload, io)
