/** Pure presentation helpers (unit-tested in src/test/format.test.ts). */

const LANGS: Record<string, { name: string; native: string; script: string }> = {
  gu: { name: "Gujarati", native: "ગુજરાતી", script: "Gujarati" },
  hi: { name: "Hindi", native: "हिन्दी", script: "Devanagari" },
  mr: { name: "Marathi", native: "मराठी", script: "Devanagari" },
  sa: { name: "Sanskrit", native: "संस्कृतम्", script: "Devanagari" },
  en: { name: "English", native: "English", script: "Latin" },
  ur: { name: "Urdu", native: "اردو", script: "Arabic" },
  fa: { name: "Persian", native: "فارسی", script: "Arabic" },
  ar: { name: "Arabic", native: "العربية", script: "Arabic" },
  bn: { name: "Bengali", native: "বাংলা", script: "Bengali" },
  ta: { name: "Tamil", native: "தமிழ்", script: "Tamil" },
  kn: { name: "Kannada", native: "ಕನ್ನಡ", script: "Kannada" },
  te: { name: "Telugu", native: "తెలుగు", script: "Telugu" },
  raj: { name: "Rajasthani", native: "राजस्थानी", script: "Devanagari" },
  kfr: { name: "Kachchi", native: "કચ્છી", script: "Gujarati" },
};

export function languageName(code: string | null | undefined): string {
  if (!code) return "Unknown";
  return LANGS[code]?.name ?? code.toUpperCase();
}

export function languageNative(code: string | null | undefined): string | null {
  return code ? (LANGS[code]?.native ?? null) : null;
}

/** BCP-47 tag for the `lang` attribute, so screen readers and fonts pick the right voice/shaping. */
export function langAttr(code: string | null | undefined): string | undefined {
  return code && /^[a-z]{2,3}$/.test(code) ? code : undefined;
}

/** Best-effort `lang` for free text with no stored language (e.g. a site's native name). */
export function scriptLang(text: string | null | undefined): string | undefined {
  if (!text) return undefined;
  if (/[\u0A80-\u0AFF]/.test(text)) return "gu";
  if (/[\u0900-\u097F]/.test(text)) return "hi";
  if (/[\u0600-\u06FF]/.test(text)) return "ur";
  return undefined;
}

export function formatYear(year: number | null | undefined): string {
  if (year === null || year === undefined) return "Undated";
  return year < 0 ? `${Math.abs(year)} BCE` : `${year} CE`;
}

export function formatEra(start: number | null | undefined, end: number | null | undefined): string {
  if (start == null && end == null) return "Undated";
  if (start != null && end != null && start !== end) {
    const sameSign = (start < 0) === (end < 0);
    return sameSign ? `${Math.abs(start)}–${formatYear(end)}` : `${formatYear(start)} – ${formatYear(end)}`;
  }
  return formatYear(start ?? end);
}

const NUM = new Intl.NumberFormat("en-IN");

export function formatNumber(n: number | null | undefined): string {
  return n == null ? "—" : NUM.format(n);
}

export function formatBytes(bytes: number | null | undefined): string {
  if (bytes == null) return "—";
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value < 10 && unit > 0 ? value.toFixed(1) : Math.round(value)} ${units[unit]}`;
}

export function formatKm(km: number | null | undefined): string {
  if (km == null) return "—";
  return km < 10 ? `${km.toFixed(1)} km` : `${NUM.format(Math.round(km))} km`;
}

export function formatPercent(ratio: number | null | undefined): string {
  return ratio == null ? "—" : `${Math.round(ratio * 100)}%`;
}

const RTF = new Intl.RelativeTimeFormat("en", { numeric: "auto" });

export function formatRelative(iso: string | null | undefined, now: number = Date.now()): string {
  if (!iso) return "—";
  const then = Date.parse(iso.endsWith("Z") || /[+-]\d\d:\d\d$/.test(iso) ? iso : `${iso}Z`);
  if (Number.isNaN(then)) return "—";
  const seconds = Math.round((then - now) / 1000);
  const abs = Math.abs(seconds);
  if (abs < 45) return seconds <= 0 ? "just now" : "in a moment";
  if (abs < 3600) return RTF.format(Math.round(seconds / 60), "minute");
  if (abs < 86400) return RTF.format(Math.round(seconds / 3600), "hour");
  return RTF.format(Math.round(seconds / 86400), "day");
}

export function formatDuration(startIso: string | null | undefined, endIso: string | null | undefined): string {
  if (!startIso || !endIso) return "—";
  const ms = Date.parse(endIso) - Date.parse(startIso);
  if (!Number.isFinite(ms) || ms < 0) return "—";
  if (ms < 1000) return `${ms} ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)} s`;
  return `${Math.floor(ms / 60_000)} m ${Math.round((ms % 60_000) / 1000)} s`;
}

const DATE = new Intl.DateTimeFormat("en-IN", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });

/** Calendar date (`YYYY-MM-DD` or ISO datetime) rendered in UTC so it never shifts a day. */
export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const t = Date.parse(/^\d{4}-\d{2}-\d{2}$/.test(iso) ? `${iso}T00:00:00Z` : iso);
  return Number.isNaN(t) ? "—" : DATE.format(t);
}

export function titleCase(s: string): string {
  return s.replace(/[-_]+/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export interface Segment {
  text: string;
  mark: boolean;
}

/**
 * Split text into plain/marked segments from `[start, end)` offsets (search highlights or entity
 * spans). Offsets are UTF-16 code units, as produced by the backend; overlapping or out-of-range
 * spans are merged and clamped rather than trusted.
 */
export function splitHighlights(text: string, spans: ReadonlyArray<ReadonlyArray<number>>): Segment[] {
  const clean = spans
    .filter((s) => s.length >= 2 && Number.isFinite(s[0]) && Number.isFinite(s[1]))
    .map(([a, b]) => [Math.max(0, Math.min(a, text.length)), Math.max(0, Math.min(b, text.length))] as const)
    .filter(([a, b]) => b > a)
    .sort((x, y) => x[0] - y[0]);
  const merged: [number, number][] = [];
  for (const [a, b] of clean) {
    const last = merged[merged.length - 1];
    if (last && a <= last[1]) last[1] = Math.max(last[1], b);
    else merged.push([a, b]);
  }
  const out: Segment[] = [];
  let cursor = 0;
  for (const [a, b] of merged) {
    if (a > cursor) out.push({ text: text.slice(cursor, a), mark: false });
    out.push({ text: text.slice(a, b), mark: true });
    cursor = b;
  }
  if (cursor < text.length || out.length === 0) out.push({ text: text.slice(cursor), mark: false });
  return out;
}

export const CATEGORY_COLORS: Record<string, string> = {
  stepwell: "#9A3412",
  temple: "#B45309",
  archaeological: "#6B4F2A",
  mosque: "#1E3A5F",
  fort: "#7C2D12",
  palace: "#7E22CE",
  craft: "#0F766E",
};

export function categoryColor(category: string | null | undefined): string {
  return (category && CATEGORY_COLORS[category]) || "#57534E";
}

export const KIND_LABELS: Record<string, string> = {
  photo: "Photograph",
  scan: "Scanned page",
  pdf: "PDF document",
  deck: "Slide deck",
  journal: "Field journal",
  story: "Oral history",
};

export function kindLabel(kind: string): string {
  return KIND_LABELS[kind] ?? titleCase(kind);
}

/** What each pipeline stage does, in the words a curator would use. */
export const JOB_LABELS: Record<string, string> = {
  extract: "Extract text & pages",
  ocr: "Read handwriting / print (OCR)",
  translate: "Translate to English",
  index: "Index for search",
  caption: "Describe photograph",
  image_embed: "Visual fingerprint",
  reconstruct3d: "Build 3D digital twin",
};

export function jobLabel(type: string): string {
  return JOB_LABELS[type] ?? titleCase(type);
}

/** The most recent run of each pipeline stage (re-indexing re-runs stages), oldest stage first. */
export function latestRuns<T extends { type: string; created_at: string }>(jobs: readonly T[]) {
  const byType = new Map<string, { job: T; runs: number }>();
  for (const job of jobs) {
    const seen = byType.get(job.type);
    if (!seen) byType.set(job.type, { job, runs: 1 });
    else byType.set(job.type, { job: job.created_at >= seen.job.created_at ? job : seen.job, runs: seen.runs + 1 });
  }
  return [...byType.values()].sort((a, b) => a.job.created_at.localeCompare(b.job.created_at));
}
