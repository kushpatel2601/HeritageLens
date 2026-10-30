# HeritageLens web app

The Next.js 16 front end of [HeritageLens](../README.md): the atlas, cross-script search, document reader, journey
story mode, 3D twin viewer, contribution flow and pipeline dashboard.

## Run

```bash
npm install
npm run dev        # http://localhost:3000; needs the API running (see the root README)
```

The app proxies `/api/*` to `API_ORIGIN` (default `http://127.0.0.1:8000`), so the browser only ever talks to
Next.js. Settings are listed in [`.env.example`](.env.example) and are read at build time.

## Scripts

| Script | What it does |
|---|---|
| `npm run dev` / `build` / `start` | Develop, build or serve the app. `predev` and `prebuild` copy MapLibre's worker into `public/vendor/` |
| `npm run lint` | ESLint |
| `npm run typecheck` | Generates route types with `next typegen`, then runs `tsc --noEmit` |
| `npm test` | Vitest unit tests in `src/test/` (jsdom) |
| `npm run gen:api` | Regenerates `src/lib/api/schema.d.ts` from `src/lib/api/openapi.json` |

## Layout

```text
src/app/          routes (App Router): /, /sites, /journeys, /search, /assets/[id], /contribute, /archive, /archive/pipeline
src/components/   UI grouped by feature (atlas, map, search, asset, journey, site, viewer, contribute, archive, ui)
src/lib/api/      OpenAPI document, generated types, typed client (openapi-fetch), TanStack Query hooks, server fetches
src/lib/          formatting, passage helpers, live SSE store, upload with progress
src/test/         Vitest tests
```

## Keeping the API types in sync

After changing backend schemas, export the OpenAPI document and regenerate the client types:

```bash
cd ../backend && python -m app.cli openapi --out ../frontend/src/lib/api/openapi.json
cd ../frontend && npm run gen:api
```

CI fails if either file is out of date.