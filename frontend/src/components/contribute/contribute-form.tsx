"use client";

import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { CircleCheck, CloudUpload, LocateFixed, X } from "lucide-react";
import Link from "next/link";
import { useId, useRef, useState, type DragEvent, type FormEvent, type ReactNode } from "react";

import { useLiveEvent } from "@/components/providers";
import { TokenField, useIngestToken } from "@/components/token-field";
import { Badge, StatusPill } from "@/components/ui/primitives";
import { KindIcon, Thumb } from "@/components/ui/thumb";
import { ApiError } from "@/lib/api/client";
import { journeysQuery, sitesQuery } from "@/lib/api/queries";
import type { UploadResult } from "@/lib/api/types";
import { formatBytes, kindLabel, languageName } from "@/lib/format";
import {
  ACCEPTED_EXTENSIONS,
  batches,
  buildForm,
  fileKey,
  isAccepted,
  uploadForm,
  type UploadFields,
} from "@/lib/upload";

const LANGUAGES = ["gu", "hi", "sa", "mr", "ur", "en"];
const LICENSES = ["CC BY 4.0", "CC BY-SA 4.0", "CC BY-NC 4.0", "CC0 1.0", "All rights reserved"];
const KIND_HINTS = [
  { value: "", title: "Detect from the file", detail: "Photos, PDFs, slide decks and journals are recognised by type." },
  { value: "scan", title: "Scanned pages", detail: "Images of handwritten or printed pages: sent to OCR, not captioned." },
  { value: "story", title: "Oral histories", detail: "Text files that transcribe a story told by a community member." },
];

function guessKind(name: string): string {
  const n = name.toLowerCase();
  if (/\.(jpe?g|png|webp|tiff?)$/.test(n)) return "photo";
  if (n.endsWith(".pdf")) return "pdf";
  if (n.endsWith(".pptx")) return "deck";
  return "journal";
}

type Tracked = UploadResult & { status: string; thumb: string | null };

export function ContributeForm() {
  const token = useIngestToken();
  const sites = useQuery(sitesQuery());
  const journeys = useQuery(journeysQuery());
  const inputId = useId();

  const [files, setFiles] = useState<File[]>([]);
  const [rejected, setRejected] = useState<string[]>([]);
  const [dragging, setDragging] = useState(false);
  const [lat, setLat] = useState("");
  const [lon, setLon] = useState("");
  const [locating, setLocating] = useState(false);
  const [progress, setProgress] = useState<number | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [tracked, setTracked] = useState<Tracked[]>([]);
  const [sentCount, setSentCount] = useState<number | null>(null);
  const abort = useRef<AbortController | null>(null);

  useLiveEvent((event) => {
    if (event.kind !== "asset") return;
    const { id, status, thumb_url } = event.data;
    setTracked((list) =>
      list.some((t) => t.asset.id === id)
        ? list.map((t) => (t.asset.id === id ? { ...t, status, thumb: thumb_url ?? t.thumb } : t))
        : list,
    );
  });

  const add = (list: FileList | null) => {
    if (!list) return;
    const incoming = [...list];
    setRejected(incoming.filter((f) => !isAccepted(f.name)).map((f) => f.name));
    setFiles((prev) => {
      const seen = new Set(prev.map(fileKey));
      return [...prev, ...incoming.filter((f) => isAccepted(f.name) && !seen.has(fileKey(f)))];
    });
  };

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDragging(false);
    add(e.dataTransfer.files);
  };

  const locate = () => {
    if (!("geolocation" in navigator)) return;
    setLocating(true);
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setLat(pos.coords.latitude.toFixed(5));
        setLon(pos.coords.longitude.toFixed(5));
        setLocating(false);
      },
      () => setLocating(false),
      { enableHighAccuracy: true, timeout: 10_000 },
    );
  };

  const submit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (!files.length || progress !== null) return;
    const data = new FormData(e.currentTarget);
    const fields: UploadFields = {
      kind: data.get("kind") as string,
      title: files.length === 1 ? (data.get("title") as string) : null,
      site_id: data.get("site_id") as string,
      journey_id: data.get("journey_id") as string,
      language: data.get("language") as string,
      contributor: data.get("contributor") as string,
      license: data.get("license") as string,
      caption: data.get("caption") as string,
      lat: lat && lon ? lat : null,
      lon: lat && lon ? lon : null,
    };
    const total = files.reduce((sum, f) => sum + f.size, 0) || 1;
    let done = 0;
    let sent = 0;
    const controller = new AbortController();
    abort.current = controller;
    setError(null);
    setSentCount(null);
    setProgress(0);
    try {
      for (const batch of batches(files)) {
        const results = await uploadForm(
          buildForm(batch, fields),
          token,
          (loaded) => setProgress(Math.min(1, (done + loaded) / total)),
          controller.signal,
        );
        done += batch.reduce((sum, f) => sum + f.size, 0);
        sent += results.length;
        setTracked((list) => [
          ...results.map((r) => ({ ...r, status: r.asset.status, thumb: r.asset.thumb_url ?? null })),
          ...list,
        ]);
        const batchKeys = new Set(batch.map(fileKey));
        setFiles((prev) => prev.filter((f) => !batchKeys.has(fileKey(f))));
      }
    } catch (err) {
      if (!(err instanceof DOMException && err.name === "AbortError")) setError(err as Error);
    } finally {
      setProgress(null);
      setSentCount(sent || null);
      abort.current = null;
    }
  };

  const authFailed = error instanceof ApiError && error.isAuth;
  const uploading = progress !== null;
  const totalBytes = files.reduce((sum, f) => sum + f.size, 0);

  return (
    <div className="grid gap-10 lg:grid-cols-[minmax(0,1fr)_380px]">
      <form onSubmit={submit} className="space-y-6" noValidate>
        <div>
          <label
            htmlFor={inputId}
            onDragOver={(e) => {
              e.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={onDrop}
            className={clsx(
              "flex cursor-pointer flex-col items-center gap-2 rounded-[var(--radius-card)] border-2 border-dashed px-6 py-10 text-center transition-colors focus-within:outline-3 focus-within:outline-offset-2 focus-within:outline-ochre",
              dragging ? "border-indigo-ink bg-indigo-soft" : "border-sandstone-dark bg-white hover:bg-sand/50",
            )}
          >
            <CloudUpload aria-hidden className="size-10 text-terracotta" />
            <span className="text-lg font-semibold">Drop files here, or click to choose</span>
            <span className="text-sm text-muted">
              Photos, scans (JPG, PNG, WebP, TIFF), PDFs, PowerPoint decks, Word and text journals · up to 50 per
              upload
            </span>
            <input
              id={inputId}
              type="file"
              multiple
              accept={ACCEPTED_EXTENSIONS.join(",")}
              className="sr-only"
              onChange={(e) => {
                add(e.target.files);
                e.target.value = "";
              }}
            />
          </label>
          {rejected.length > 0 && (
            <p role="alert" className="mt-2 text-sm text-danger">
              Not a supported type, skipped: {rejected.join(", ")}
            </p>
          )}
          {files.length > 0 && (
            <div className="mt-3">
              <p className="mb-2 text-sm text-muted">
                {files.length} {files.length === 1 ? "file" : "files"} · {formatBytes(totalBytes)}
                <button type="button" className="ml-3 font-semibold text-terracotta underline" onClick={() => setFiles([])}>
                  Clear
                </button>
              </p>
              <ul className="max-h-64 divide-y divide-sand overflow-y-auto rounded-lg border border-sandstone bg-white">
                {files.map((f) => (
                  <li key={fileKey(f)} className="flex items-center gap-3 px-3 py-2 text-sm">
                    <KindIcon kind={guessKind(f.name)} className="size-4 shrink-0 text-muted" />
                    <span className="min-w-0 flex-1 truncate">{f.name}</span>
                    <span className="shrink-0 text-xs text-muted tabular-nums">{formatBytes(f.size)}</span>
                    <button
                      type="button"
                      className="rounded p-1 text-muted hover:bg-sand hover:text-ink"
                      aria-label={`Remove ${f.name}`}
                      onClick={() => setFiles((prev) => prev.filter((p) => p !== f))}
                    >
                      <X aria-hidden className="size-4" />
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>

        <fieldset>
          <legend className="mb-2 text-sm font-semibold">What are these?</legend>
          <div className="grid gap-2 sm:grid-cols-3">
            {KIND_HINTS.map((k) => (
              <label
                key={k.value}
                className="flex cursor-pointer gap-2 rounded-lg border border-sandstone bg-white p-3 has-checked:border-indigo-ink has-checked:ring-1 has-checked:ring-indigo-ink"
              >
                <input
                  type="radio"
                  name="kind"
                  value={k.value}
                  defaultChecked={!k.value}
                  className="mt-1 accent-indigo-ink"
                />
                <span>
                  <span className="block text-sm font-semibold">{k.title}</span>
                  <span className="block text-xs text-muted">{k.detail}</span>
                </span>
              </label>
            ))}
          </div>
        </fieldset>

        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Title" hint={files.length > 1 ? "Only for single uploads; file names are used" : "Optional"}>
            {(id) => (
              <input id={id} name="title" maxLength={300} className="field" disabled={files.length > 1} />
            )}
          </Field>
          <Field label="Language of the text" hint="Leave on auto-detect unless you know">
            {(id) => (
              <select id={id} name="language" className="field" defaultValue="">
                <option value="">Auto-detect</option>
                {LANGUAGES.map((l) => (
                  <option key={l} value={l}>
                    {languageName(l)}
                  </option>
                ))}
              </select>
            )}
          </Field>
          <Field label="Heritage site" hint="Links the items and places them on the map">
            {(id) => (
              <select id={id} name="site_id" className="field" defaultValue="" disabled={sites.isPending}>
                <option value="">{sites.isPending ? "Loading sites…" : "Detect from content / none"}</option>
                {sites.data?.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
              </select>
            )}
          </Field>
          <Field label="Expedition" hint="Optional field journey these belong to">
            {(id) => (
              <select id={id} name="journey_id" className="field" defaultValue="" disabled={journeys.isPending}>
                <option value="">None</option>
                {journeys.data?.map((j) => (
                  <option key={j.id} value={j.id}>
                    {j.title} ({j.year})
                  </option>
                ))}
              </select>
            )}
          </Field>
          <Field label="Your name" hint="Credited as the contributor">
            {(id) => <input id={id} name="contributor" maxLength={120} className="field" autoComplete="name" />}
          </Field>
          <Field label="Licence">
            {(id) => (
              <select id={id} name="license" className="field" defaultValue={LICENSES[0]}>
                {LICENSES.map((l) => (
                  <option key={l}>{l}</option>
                ))}
              </select>
            )}
          </Field>
        </div>

        <Field label="Caption or description" hint="Applies to every file in this upload">
          {(id) => <textarea id={id} name="caption" maxLength={1000} rows={3} className="field" />}
        </Field>

        <fieldset>
          <legend className="mb-2 text-sm font-semibold">
            Location <span className="font-normal text-muted">(otherwise read from photo GPS, the site, or the text)</span>
          </legend>
          <div className="flex flex-wrap items-end gap-3">
            <Field label="Latitude" className="w-36">
              {(id) => (
                <input
                  id={id}
                  inputMode="decimal"
                  value={lat}
                  onChange={(e) => setLat(e.target.value)}
                  className="field"
                  placeholder="23.8589"
                />
              )}
            </Field>
            <Field label="Longitude" className="w-36">
              {(id) => (
                <input
                  id={id}
                  inputMode="decimal"
                  value={lon}
                  onChange={(e) => setLon(e.target.value)}
                  className="field"
                  placeholder="72.1016"
                />
              )}
            </Field>
            <button type="button" className="btn btn-ghost" onClick={locate} disabled={locating}>
              <LocateFixed aria-hidden className={clsx("size-4", locating && "animate-pulse")} />
              {locating ? "Locating…" : "Use my location"}
            </button>
          </div>
        </fieldset>

        <TokenField forceOpen={authFailed} />

        <div className="space-y-3">
          {uploading && (
            <div>
              <div
                role="progressbar"
                aria-label="Upload progress"
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={Math.round((progress ?? 0) * 100)}
                className="h-2 overflow-hidden rounded-full bg-sand"
              >
                <div
                  className="h-full bg-terracotta transition-[width] duration-200"
                  style={{ width: `${(progress ?? 0) * 100}%` }}
                />
              </div>
              <p className="mt-1 text-xs text-muted tabular-nums">{Math.round((progress ?? 0) * 100)}% uploaded</p>
            </div>
          )}
          <div className="flex flex-wrap items-center gap-3">
            <button type="submit" className="btn btn-primary" disabled={!files.length || uploading}>
              <CloudUpload aria-hidden className="size-4" />
              {uploading ? "Uploading…" : `Add ${files.length || ""} to the archive`}
            </button>
            {uploading && (
              <button type="button" className="btn btn-ghost" onClick={() => abort.current?.abort()}>
                Cancel
              </button>
            )}
          </div>
          {error && (
            <p role="alert" className="text-sm text-danger">
              {error.message}
            </p>
          )}
          {sentCount !== null && !uploading && (
            <p role="status" className="flex items-center gap-1.5 text-sm text-moss">
              <CircleCheck aria-hidden className="size-4 shrink-0" />
              <span>
                {sentCount === 1 ? "1 item" : `${sentCount} items`} added and now being processed.{" "}
                <a href="#received-panel" className="font-semibold underline">
                  Follow progress
                </a>
              </span>
            </p>
          )}
        </div>
      </form>

      <aside className="space-y-6">
        <section aria-labelledby="received" className="card scroll-mt-24 p-4" id="received-panel">
          <h2 id="received" className="mb-3 text-lg font-semibold">
            Received
          </h2>
          {tracked.length ? (
            <ul className="space-y-2" aria-live="polite">
              {tracked.map((t) => (
                <li key={t.asset.id} className="flex items-center gap-3">
                  <Thumb src={t.thumb} alt="" kind={t.asset.kind} className="size-12 shrink-0 rounded-md" />
                  <div className="min-w-0 flex-1">
                    <Link href={`/assets/${t.asset.id}`} className="block truncate text-sm font-semibold hover:underline">
                      {t.asset.title}
                    </Link>
                    <span className="flex items-center gap-1.5 text-xs text-muted">
                      {kindLabel(t.asset.kind)}
                      {!t.created && <Badge>Already in the archive</Badge>}
                    </span>
                  </div>
                  <StatusPill status={t.status} />
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-muted">
              Uploaded items appear here and update live as the pipeline reads, translates and indexes them.
            </p>
          )}
          {tracked.length > 0 && (
            <Link href="/archive/pipeline" className="mt-3 inline-block text-sm font-semibold text-indigo-ink underline">
              Watch the pipeline
            </Link>
          )}
        </section>
        <WhatHappens />
      </aside>
    </div>
  );
}

function Field({
  label,
  hint,
  className,
  children,
}: {
  label: string;
  hint?: string;
  className?: string;
  children: (id: string) => ReactNode;
}) {
  const id = useId();
  return (
    <div className={className}>
      <label htmlFor={id} className="mb-1 block text-sm font-semibold">
        {label}
      </label>
      {children(id)}
      {hint && <p className="mt-1 text-xs text-muted">{hint}</p>}
    </div>
  );
}

const STEPS: { title: string; detail: string; gpu?: boolean }[] = [
  { title: "Checked and stored", detail: "File type verified by content; exact duplicates are recognised by SHA-256." },
  { title: "Text extracted", detail: "Born-digital text is read directly; PDFs and decks are split into pages." },
  { title: "Handwriting read", detail: "Scans go to multilingual OCR for Gujarati, Devanagari and Latin.", gpu: true },
  { title: "Translated", detail: "Regional-language passages are translated to English.", gpu: true },
  { title: "Indexed and mapped", detail: "Places and dates are recognised; items appear on the atlas and in search." },
  { title: "Photos described", detail: "Captions and visual fingerprints make photos searchable by content.", gpu: true },
];

function WhatHappens() {
  return (
    <section aria-labelledby="what-next" className="card p-4">
      <h2 id="what-next" className="mb-3 text-lg font-semibold">
        What happens next
      </h2>
      <ol className="space-y-3">
        {STEPS.map((s, i) => (
          <li key={s.title} className="flex gap-3">
            <span
              aria-hidden
              className="flex size-6 shrink-0 items-center justify-center rounded-full bg-terracotta-soft text-xs font-bold text-terracotta-dark"
            >
              {i + 1}
            </span>
            <div>
              <p className="text-sm font-semibold">
                {s.title}
                {s.gpu && (
                  <Badge tone="indigo" className="ml-2 align-middle">
                    GPU
                  </Badge>
                )}
              </p>
              <p className="text-xs text-muted">{s.detail}</p>
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}
