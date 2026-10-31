# HeritageLens · Project status

**Competition:** HackCult ’26, IIT Gandhinagar, Track 2, **HC26-CULT01**: Digital Revitalisation of Unstructured
Cultural & Architectural Heritage Archives.
**Deadline:** 4 November 2026, 6:30 PM IST.
**Last updated:** 31 October 2026.

**Judging weights:**

| Criterion | Weight |
|---|---|
| Technical Execution & Code Quality | 40% |
| System Architecture & Scalability | 30% |
| UI/UX | 20% |
| Innovation & Problem Fit | 10% |

**Overall progress:** the build is **100% done and deployed for free**. The backend, GPU worker and frontend are
finished, tested, and checked in a browser on desktop and at phone width. CI, the READMEs and the git history are done
too. Only your own submission tasks remain (section 3F).

**Live:** web <https://heritagelens-hc26.vercel.app> · API <https://heritagelens-hc26.onrender.com> (Render free plan
for the API, Vercel Hobby for the web app; see section 3E). GPU work still runs on Google Colab.

---

## 1. What HeritageLens does

The project covers all three pathways from the problem statement:

1. **Regional text archives.** Gujarati, Hindi, Marathi and Sanskrit scans, PDFs, DOCX and PPTX files are read with
   OCR, translated to English, and made searchable with cross-script hybrid search. For example, વાવ, बावड़ी
   and "vav" all find the same stepwells.
2. **Interactive atlas.** A map of sites, expedition routes and geotagged photographs, plus journey "story mode".
3. **3D digital twins.** Built from a site's photos on a Colab GPU and explorable in the browser.

**Components:**

```text
Browser (Next.js 16) ──▶ FastAPI backend ──▶ SQLite or PostgreSQL + file storage
        ▲    SSE live updates  │  job queue (CPU / GPU)
        └──────────────────────┘
                               ▲  pull-based HTTPS (no open ports)
                    Colab GPU worker (T4 / A100 / H100): OCR, translation, captions, 3D twins
```

---

## 2. Completed ✅

### Backend: `backend/`, finished and verified

- [x] FastAPI app with typed Pydantic schemas and an OpenAPI export, organised into `api/`, `core/`, `db/`,
      `schemas/`, `services/`, `workers/` and `seed/`.
- [x] Database: SQLite by default; PostgreSQL with Alembic migrations, verified working.
- [x] Ingestion:
  - Multipart upload of up to 50 files per request, checked by magic bytes, with de-duplication.
  - Accepted types: JPG, PNG, WEBP, TIFF, PDF, PPTX, DOCX, TXT and MD.
- [x] Extraction:
  - Born-digital text is extracted directly; OCR is only queued when a page needs it.
  - Pages, chunks, and entity extraction for places, sites and dates.
  - Geotags from EXIF, from manual entry, or inferred from the linked site or a mentioned place.
- [x] Job queue:
  - Separate CPU and GPU queues with leases, heartbeats, retries with backoff, and dead-lettering.
  - Retry and reprocess endpoints.
- [x] Hybrid search:
  - Keyword (FTS), semantic (multilingual embeddings) and phonetic cross-script matching, fused with RRF.
  - Facets, highlighted snippets and query interpretation.
  - Photo search by text using CLIP.
- [x] Sites, journeys and routes; GeoJSON layers; 3D twin requests and twin records.
- [x] Server-Sent Events stream for live pipeline updates. Job events and the `/jobs` endpoints name what each job
      works on (`asset_title`, `site_name`, `site_slug`), so the dashboard shows titles instead of ids.
- [x] Seed data: 17 sites, 3 journeys and 57 assets (43 photos, 7 journals, 4 scans, 2 stories, 1 deck), in English,
      Gujarati and Hindi.
- [x] CLI: `migrate`, `seed`, `worker`, `reindex`, `openapi`, `serve`.
- [x] Quality gate: **143 tests passing** (85% coverage); ruff, ruff format and mypy are clean.

### GPU worker: `ml/` and `notebooks/`, finished and verified

- [x] `heritage_gpu` package. It leases jobs from the server, sends heartbeats, posts results back, and hands its
      job back to the queue when stopped.
- [x] Engines:

  | Job | Engine |
  |---|---|
  | OCR | Tesseract with `tessdata_best` Indic models, or Qwen2.5-VL-3B |
  | Translation | IndicTrans2, falling back to NLLB-200 |
  | Captions | BLIP |
  | 3D twins | Depth Anything V2 relief, or COLMAP + gsplat Gaussian splatting |

- [x] `--fake` mode: model-free engines for demos and tests; the CLI also has `check` and `selftest` commands.
- [x] `notebooks/heritage_gpu_worker.ipynb`: step-by-step Colab notebook for T4, A100 or H100.
- [x] Quality gate: **119 tests passing**.

### Frontend: `frontend/`, finished and verified

- [x] Foundation:
  - Typed API client generated from OpenAPI, with TanStack Query.
  - Live SSE store that batches cache refreshes.
  - Design system: parchment, terracotta and indigo theme, built with Tailwind v4.
  - App shell, MapLibre atlas map and a three.js 3D twin viewer.
- [x] Pages. All of them typecheck, build, and were checked in a browser at 1366 px and at phone width (360–375 px)
      with no sideways scrolling:

  | Route | Page |
  |---|---|
  | `/` | Atlas home: map with sites, routes and geotagged items |
  | `/sites` | Sites list |
  | `/sites/[slug]` | Site detail with the 3D twin builder |
  | `/journeys` | Journeys list |
  | `/journeys/[slug]` | Journey story mode |
  | `/search` | Cross-script search with facets, highlights and translations |
  | `/assets/[id]` | Document reader: side-by-side original and English, entity highlights, provenance, map, pipeline |
  | `/contribute` | Drag-and-drop upload with progress, geolocation and live status |
  | `/archive` | Filterable collection browser |
  | `/archive/pipeline` | Queue stats, jobs table with retry, workers, live feed, Colab instructions |

- [x] Helper libraries: `lib/format.ts`, `lib/passages.ts` and `lib/upload.ts`.

---

## 3. Remaining ⏳

Listed in priority order, with estimates.

### A. Frontend verification ✅ done

- [x] `npm run typecheck` is clean. The fix was a `Received<T>` type in `lib/api/types.ts`, which mirrors how
      openapi-fetch widens tuples such as `bbox` and `highlights`.
- [x] `npm run lint` is clean. The vendored MapLibre worker in `public/vendor/` is now excluded from lint.
- [x] `npm run build` succeeds with all 13 routes.
- [x] All lucide icons exist; tsc would fail otherwise.
- [x] Every page opened in a browser: search for `વાવ`, assets 41 and 1, an upload on `/contribute`, archive
      filters, and the pipeline page. Bugs found and fixed:
  - 3D viewer crashed on a drei `<Html>` label.
  - Journey map rendered 0 px tall.
  - Map attribution covered the map on narrow screens.
  - Photo passages repeated the same text (fixed in the backend, with a test).
  - Western India map bounds were off.
  - Small text fixes: "1 workers", a language badge naming the same language twice, the upload success message.
  - Pipeline card now shows the latest run of each step.
  - Jobs table and live feed showed "Item 58"; they now show the item title or site name, linked.
- [x] Live updates (SSE) stream through the Next.js `/api` rewrite: the feed and jobs table updated live while a
      worker drained the GPU queue.
- [x] Phone layout at 360–375 px: no page scrolls sideways. Fixes: the atlas side panel was stretched by its
      content; the jobs table now folds status and timing into the first column; the compact nav hides its
      scrollbar.

### B. Frontend unit tests ✅ done

- [x] `vitest.config.mts`: jsdom environment, the `@/` path alias and `@vitejs/plugin-react`.
- [x] **56 tests passing** in `src/test/`:

  | File | Covers |
  |---|---|
  | `format.test.ts` | highlights, eras, dates, durations, scripts, languages, byte sizes |
  | `passages.test.ts` | stripping overlap between chunks, entity offsets, splitting text into entity pieces |
  | `upload.test.ts` | file types, batching, form building, XHR upload (progress, errors, cancel) |
  | `live.test.ts` | which caches each event refreshes, batching of event bursts, feed cap, connection sharing, reconnect with backoff |
  | `highlighted.test.tsx` | `<mark>` rendering and ellipses in search snippets |
  | `relative-time.test.tsx` | relative times hydrate cached HTML without a mismatch, then refresh |

### C. CI and documentation ✅ done

- [x] `.github/workflows/ci.yml`, tests only with no deploy step. It runs on pushes to `main`, on pull requests, and
      by hand:
  - Backend: ruff, ruff format, mypy, an OpenAPI drift check, and pytest with coverage (85%).
  - ML: ruff, mypy, pytest.
  - Frontend: lint, typecheck, test, build. The build needs no running API.
- [x] Every CI step was run locally in a fresh Python 3.12 venv; all passed. Two bugs found and fixed:
  - `pip install -e backend` failed because `pyproject.toml` pointed its readme outside the folder. Added
    `backend/README.md`.
  - mypy failed in CI on a `type: ignore` that is only needed when fastembed is installed
    (`app/services/embeddings.py`). It is now marked `unused-ignore`, so it passes either way.
- [x] `backend/.env.example` (all `HL_*` settings) and `frontend/.env.example` (`API_ORIGIN`, Colab link).
- [x] Root `README.md`:
  - The problem, the three pathways, and a table mapping the project to the judging criteria.
  - Two **Mermaid diagrams** (architecture and pipeline), both checked to render.
  - Six screenshots in `docs/screenshots/`.
  - Local setup without Docker, Colab worker steps, the test table (318 tests), project layout, the live links and
    a "Deploy it free" section.
  - Credits and licences for models and data, with commercial-use alternatives.
- [x] `backend/README.md` and a new `frontend/README.md`, replacing the create-next-app default.
- [x] Notebook step 4 now says `python -m app.cli serve`; all Docker mentions removed.

### D. Cleanup and commit ✅ done

- [x] `.gitignore` covers `backend/var/`, `backend/var-*/`, `.coverage`, caches, `.venv/`, `__pycache__/`,
      `node_modules/`, `.next/` and `tsconfig.tsbuildinfo`.
- [x] First git commit on `main`. No file in it is over 1 MB.

### E. Free deployment ✅ done

- [x] **API on Render** (free web service, Singapore): <https://heritagelens-hc26.onrender.com>, built from
      `render.yaml` → `deploy/render/Dockerfile`.
  - 512 MB RAM fits because search uses a lean ONNX export of the multilingual embedder. It gives identical
    vectors and the whole API uses about 250 MB. CLIP photo search is off; it alone would need about 350 MB more.
  - The embedder warms up in the background at start, so the first search is fast.
  - The image carries a snapshot of the local archive, including the Colab results: captions, OCR, translations
    and the real 3D twins. It is downloaded from the `deploy-assets` release and pinned by SHA-256 in
    `deploy/render/assets.lock.json`. The disk is ephemeral, so every restart begins again from this snapshot.
  - `HL_WORKER_TOKEN` is generated by Render. Copy it from the service's **Environment** tab into Colab as
    `HERITAGE_TOKEN`, with `HERITAGE_API_URL=https://heritagelens-hc26.onrender.com`. No tunnel is needed.
  - The `keep-alive` workflow pings `/api/v1/health` every 5 minutes (repository variable `API_URL`), so the
    free service doesn't sleep.
- [x] **Web app on Vercel** (Hobby): <https://heritagelens-hc26.vercel.app>, project `heritagelens-hc26`.
  - Deploy with `cd frontend; npx vercel deploy --prod`. It is not connected to git, so pushes don't redeploy it.
  - Environment: `API_ORIGIN` and `NEXT_PUBLIC_WORKER_API_URL` (both the Render URL), and `NEXT_PUBLIC_COLAB_URL`.
  - `frontend/vercel.json` sets the Next.js preset; without it the site returned 404.
- [x] Verified live:
  - `deploy/render/smoke_test.py` passes 31 of 31 checks. Search takes 16–76 ms on the server; 2.4 MB twins load
    in about 1 s from Vercel's edge cache.
  - Browser checks with 0 console errors: atlas, site page with its 3D twin, Gujarati search, journey story mode,
    asset page, contribute, and the live pipeline (SSE connected). Phone width shows no sideways scrolling.
  - Upload bodies of 8 MB pass through the Vercel proxy.

### F. Your tasks · cannot be automated

Done:

- [x] Public repository: https://github.com/kushpatel2601/HeritageLens, branch `main`.
- [x] `YOUR-USERNAME` replaced with `kushpatel2601` in the README badges, the notebook's `REPO_URL` and
      `frontend/.env.example`.
- [x] CI is green on GitHub: backend, GPU worker and frontend jobs all pass.
- [x] Ran the real GPU worker once on a Colab T4, through a `cloudflared` tunnel. It finished 14 jobs with 0 failures:
  - OCR of asset 53 (Tesseract 5) and its translation (NLLB-200; IndicTrans2 did not load in Colab).
  - BLIP captions for assets 55–57.
  - Real 3D twins (Depth Anything V2 depth reliefs) for Rani ki Vav, Adalaj, Chand Baori, Modhera, Hampi, Dada
    Harir, Toorji ka Jhalra and Agrasen ki Baoli. Each site page shows these first, ahead of the procedural demos.
  - These results live in your local database (`backend/var/`, not in git) and in the deployed snapshot. Don't
    re-seed or delete `backend/var/` before the demo; if you do, run the Colab worker again.
- [x] Demo video recorded (2:59, narrated, captioned): `frontend/public/demo/heritagelens-demo.mp4`, shown on the home
      page at `/#demo` and linked from the README.

Still to do:

| Task | Time |
|---|---|
| Make the pitch deck (**at most 10 slides**) | ~2 h |
| Submit on the HackCult portal before **4 Nov 2026, 6:30 PM IST**, with the repository, live demo and demo video links | — |

**Estimated time left:** no build work; about 2–3 h of your own tasks (deck, submission).

---

## 4. Running it locally (Windows PowerShell)

### First-time setup (~15–20 min)

```powershell
# Backend
cd backend
python -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[ml,dev]"
$env:PYTHONPATH = "."
.\.venv\Scripts\python -m app.cli migrate
.\.venv\Scripts\python -m app.cli seed

# Frontend
cd ..\frontend
npm install
```

### Every time

```powershell
# Terminal 1: API on port 8010. Port 8000 is used by another program on this PC.
cd backend; $env:PYTHONPATH = "."; .\.venv\Scripts\python -m app.cli serve --port 8010

# Terminal 2: web app on http://localhost:3000
cd frontend; $env:API_ORIGIN = "http://127.0.0.1:8010"; npm run dev
```

> ⚠️ **Do not run the fake GPU worker (`heritage_gpu run --fake`) against your real database.** It completes the
> seed's waiting GPU jobs with made-up output: asset 53 gets fake OCR text, and assets 55–57 get fake captions. For
> the demo, run the real worker on Colab instead. To try the fake worker safely, stop the API, copy `backend\var` to
> `backend\var-demo`, then start a second API that uses the copy:
>
> ```powershell
> cd backend; $env:PYTHONPATH = "."
> $env:HL_DATABASE_URL = "sqlite+aiosqlite:///./var-demo/heritagelens.db"; $env:HL_STORAGE_DIR = "var-demo/storage"
> .\.venv\Scripts\python -m app.cli serve --port 8011
> # In another terminal:
> cd ml; ..\backend\.venv\Scripts\python -m heritage_gpu run --fake --api-url http://127.0.0.1:8011 --token dev-worker-token
> ```

`dev-worker-token` is the default value of the server's `HL_WORKER_TOKEN` setting. If you change that setting, pass
the new value to `--token`.

### Checks

```powershell
# Backend
cd backend; $env:PYTHONPATH = "."
.\.venv\Scripts\python -m pytest -q
.\.venv\Scripts\python -m ruff check .
.\.venv\Scripts\python -m mypy app

# ML
cd ml; $env:PYTHONPATH = (Get-Location).Path
..\backend\.venv\Scripts\python -m pytest -q tests

# Frontend
cd frontend
npm run typecheck
npm run lint
npm test
$env:API_ORIGIN = "http://127.0.0.1:8010"; npm run build
```

---

## 5. Notes for whoever continues

- **Windows PowerShell 5** does not support `&&`. Use `;` to chain commands.
- After changing backend schemas, regenerate the frontend types:
  1. Run `python -m app.cli openapi` and save the output to `frontend/src/lib/api/openapi.json`.
  2. Run `npm run gen:api`.
- `API_ORIGIN` is fixed when the frontend is built, so set it before `npm run dev` or `npm run build`.
- **lucide-react v1 renamed icons.** Use `LoaderCircle`, `CircleCheck`, `CircleX`, `TriangleAlert` and
  `CloudUpload`. The old names (`Loader2`, `CheckCircle2`, `XCircle`, `AlertTriangle`, `UploadCloud`, `Filter`) do
  not exist.
- MapLibre's worker file is copied to `public/vendor/` by `scripts/copy-vendor.mjs`, which runs automatically before
  `dev` and `build`.
- **Sample data for demos:**

  | Asset | Contents |
  |---|---|
  | 41 | Hindi journal with English translations and entities (Patan, Rani ki Vav, 1063 CE) |
  | 1 | Photograph with a contributor caption |

  Good search queries: `વાવ`, `बावड़ी`, `vav`, `stepwell`.
