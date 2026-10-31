# HeritageLens API on Render's free web service (512 MB RAM, shared CPU, ephemeral disk).
# Built from the repository root (render.yaml: dockerContext ".", dockerfilePath ./deploy/render/Dockerfile):
#   docker build -f deploy/render/Dockerfile -t heritagelens-api .
#   docker run --rm -p 10000:10000 --memory 512m heritagelens-api
FROM python:3.12-slim

# Tesseract with the Indic packs the CPU OCR fallback uses, so uploads are OCR'd even while the Colab
# GPU worker is offline. Captions, translation and 3D twins wait in the GPU queue for that worker.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      tesseract-ocr tesseract-ocr-eng tesseract-ocr-hin tesseract-ocr-guj tesseract-ocr-mar tesseract-ocr-san \
 && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 1000 app
USER app
ENV HOME=/home/app \
    PATH=/home/app/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /home/app/heritagelens

# Dependencies first (editable install against a stub package) so code-only deploys reuse this layer.
# `lean` = onnxruntime + sentencepiece: no fastembed, tokenizers or CLIP in a 512 MB box.
COPY --chown=app backend/pyproject.toml backend/README.md backend/
RUN mkdir -p backend/app && touch backend/app/__init__.py \
 && pip install --user -e "./backend[lean,ocr]"

# Archive snapshot (SQLite + object storage) and the lean text model, pinned by SHA-256 in the lock file
# and published by build_assets.py. The disk is ephemeral: every restart begins again from this snapshot.
COPY --chown=app deploy/render/fetch_assets.py deploy/render/assets.lock.json deploy/render/
RUN python deploy/render/fetch_assets.py

COPY --chown=app backend/app backend/app

# Search embeds queries with the lean export (identical vectors to fastembed, ~250 MB for the whole API);
# photo search (CLIP) is off because it alone needs ~350 MB more.
ENV HL_ENV=prod \
    HL_EMBEDDER=lean \
    HL_ENABLE_IMAGE_SEARCH=false \
    HL_EMBED_THREADS=1 \
    HL_WARM_EMBEDDER=true \
    HL_EMBEDDED_WORKER_CONCURRENCY=1 \
    HL_MAX_UPLOAD_MB=10 \
    HL_MAX_PDF_PAGES=40 \
    HL_LOG_JSON=true \
    MALLOC_ARENA_MAX=2 \
    OMP_NUM_THREADS=1
WORKDIR /home/app/heritagelens/backend
EXPOSE 10000
CMD ["sh", "-c", "exec python -m app.cli serve --host 0.0.0.0 --port ${PORT:-10000}"]
