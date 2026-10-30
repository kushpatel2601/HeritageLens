// Copies MapLibre's web-worker bundle into public/ so it is served same-origin.
// maplibre-gl v6 resolves its worker relative to import.meta.url, which no longer points at
// node_modules once the library is bundled; the map calls setWorkerUrl("/vendor/...") instead.
// Runs on postinstall/predev/prebuild so the worker always matches the installed library version.
import { copyFileSync, mkdirSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const require = createRequire(join(root, "package.json"));
const pkgDir = dirname(require.resolve("maplibre-gl/package.json"));
const outDir = join(root, "public", "vendor");

mkdirSync(outDir, { recursive: true });
copyFileSync(join(pkgDir, "dist", "maplibre-gl-worker.mjs"), join(outDir, "maplibre-gl-worker.mjs"));
console.log("copied maplibre-gl-worker.mjs -> public/vendor/");
