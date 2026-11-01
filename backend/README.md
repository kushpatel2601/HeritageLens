# heritagelens-api: the HeritageLens backend

FastAPI service for [HeritageLens](../README.md). It ingests heritage archives, runs the processing pipeline,
serves hybrid cross-script search, and hands GPU work to pull-based [`heritage-gpu`](../ml/README.md) workers.

## Run

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[ml,dev]"
python -m app.cli migrate
python -m app.cli seed
python -m app.cli serve          # http://127.0.0.1:8000, interactive docs at /docs
```

| Extra | Adds |
|---|---|
| `ml` | fastembed: multilingual sentence embeddings and CLIP photo search on CPU (ONNX, no torch) |
| `s3` | boto3, for S3 or MinIO storage |
| `ocr` | pytesseract, so OCR can run on the server's CPU when the `tesseract` binary is installed |
| `dev` | pytest, pytest-cov, ruff and mypy |

Settings are environment variables prefixed `HL_` (or a `.env` file in the directory you start from). All of
them are documented in [`.env.example`](.env.example). The defaults run everything locally on SQLite.

## CLI

| Command | What it does |
|---|---|
| `migrate [--revision head]` | Create or upgrade the database schema (Alembic on PostgreSQL) |
| `seed [--offline] [--no-process]` | Load the sample archive. Idempotent |
| `serve [--host] [--port] [--reload]` | Run the API with uvicorn. A CPU worker runs inside it unless `HL_EMBEDDED_WORKER=false` |
| `worker [--concurrency N] [--name]` | Run an extra CPU worker process against the same database |
| `reindex [--sites-only] [--no-process]` | Re-embed sites and re-index every asset, for example after changing the embedder |
| `openapi [--out FILE]` | Export the OpenAPI document that types the frontend client |

The same commands are installed as the `heritagelens` script.

## Layout

```text
app/api/routes/      assets, search, sites, journeys, twins, jobs, workers, ops (health, ready, stats, SSE)
app/core/            settings, structured logging, error model, auth for ingest and worker tokens
app/db/              SQLAlchemy models; SQLite or PostgreSQL + pgvector (HNSW indexes)
app/schemas/         Pydantic request and response models
app/services/        ingest, extractors (PDF, PPTX, DOCX, text, images), pipeline handlers, job queue,
                     hybrid search, text processing (scripts, phonetic keys, entities), storage, geo, twins
app/workers/         in-process and standalone CPU workers
app/seed/            sample archive: 17 sites, 3 journeys, 59 assets
migrations/          Alembic migrations
tests/               pytest suite (hermetic: hashing embedder, no network)
```

## Checks

```bash
ruff check app tests && ruff format --check app tests
mypy app
pytest --cov
```
