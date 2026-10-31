"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import {
  Calendar,
  ChevronLeft,
  ChevronRight,
  Cpu,
  Download,
  ExternalLink,
  Languages,
  MapPin,
  RefreshCw,
  RotateCcw,
  Sparkles,
  TriangleAlert,
  Zap,
} from "lucide-react";
import Link from "next/link";
import { useState, type ReactNode } from "react";

import { AssetGrid } from "@/components/asset-grid";
import { AtlasMap } from "@/components/map";
import { TokenField, useIngestToken } from "@/components/token-field";
import { Badge, EmptyState, StatusPill } from "@/components/ui/primitives";
import { RelativeTime } from "@/components/ui/relative-time";
import { api, ApiError, authHeaders, unwrap } from "@/lib/api/client";
import { assetQuery, chunksQuery, keys } from "@/lib/api/queries";
import type { AssetDetail, AssetsGeoJSON, Chunk, Entity, Job, PageOut } from "@/lib/api/types";
import {
  formatBytes,
  formatDate,
  formatDuration,
  formatNumber,
  formatPercent,
  formatYear,
  jobLabel,
  kindLabel,
  langAttr,
  languageName,
  languageNative,
  latestRuns,
  titleCase,
} from "@/lib/format";
import { entitySpans, splitEntities, toPassages, type Passage } from "@/lib/passages";

type Mode = "both" | "original" | "english";

const BROWSER_IMAGES = /^image\/(jpeg|png|webp|gif|avif)$/;

function isBusy(asset: AssetDetail | undefined): boolean {
  if (!asset) return false;
  return (
    asset.status === "queued" ||
    asset.status === "processing" ||
    asset.jobs.some((j) => j.status === "queued" || j.status === "leased")
  );
}

export function AssetView({
  initial,
  initialChunks,
  initialPage,
}: {
  initial: AssetDetail;
  initialChunks: Chunk[];
  initialPage: number;
}) {
  const { data: asset } = useQuery({
    ...assetQuery(initial.id),
    initialData: initial,
    // SSE invalidates this key as jobs progress; polling is only a fallback if the stream drops.
    refetchInterval: (q) => (isBusy(q.state.data) ? 5_000 : false),
  });
  const { data: chunks } = useQuery({ ...chunksQuery(initial.id), initialData: initialChunks });
  const isPhoto = asset.kind === "photo";
  const native = languageNative(asset.language);
  const showNative = native && native !== languageName(asset.language);

  return (
    <div className="mx-auto w-full max-w-7xl px-4 py-8">
      <nav aria-label="Breadcrumb" className="mb-4 text-sm text-muted">
        <ol className="flex flex-wrap items-center gap-1">
          <li>
            <Link href="/archive" className="hover:text-ink hover:underline">
              Archive
            </Link>
          </li>
          {asset.site_slug && (
            <li className="flex items-center gap-1">
              <ChevronRight aria-hidden className="size-3.5" />
              <Link href={`/sites/${asset.site_slug}`} className="hover:text-ink hover:underline">
                {asset.site_name}
              </Link>
            </li>
          )}
          <li className="flex min-w-0 items-center gap-1">
            <ChevronRight aria-hidden className="size-3.5" />
            <span aria-current="page" className="truncate text-ink-soft">
              {asset.title}
            </span>
          </li>
        </ol>
      </nav>

      <header className="mb-8 flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="eyebrow mb-1">{kindLabel(asset.kind)}</p>
          <h1 className="text-3xl font-semibold text-balance sm:text-4xl">{asset.title}</h1>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <StatusPill status={asset.status} />
            {asset.language && (
              <Badge tone="indigo">
                <Languages aria-hidden className="size-3" />
                {languageName(asset.language)}
                {showNative && <span lang={asset.language}> · {native}</span>}
              </Badge>
            )}
            {asset.era_year != null && (
              <Badge tone="ochre">
                <Calendar aria-hidden className="size-3" />
                {formatYear(asset.era_year)}
              </Badge>
            )}
            {!isPhoto && asset.language && asset.language !== "en" && asset.translated_ratio > 0 && (
              <Badge tone="moss">{formatPercent(asset.translated_ratio)} translated</Badge>
            )}
          </div>
        </div>
        <a href={asset.original_url} download={asset.original_filename} className="btn btn-secondary">
          <Download aria-hidden className="size-4" /> Original
          <span className="text-xs text-muted">{formatBytes(asset.size_bytes)}</span>
        </a>
      </header>

      {asset.status === "failed" && asset.error && (
        <div role="alert" className="mb-6 flex gap-3 rounded-lg border border-danger/30 bg-danger-soft p-4 text-sm">
          <TriangleAlert aria-hidden className="size-5 shrink-0 text-danger" />
          <div>
            <p className="font-semibold text-danger">Processing failed</p>
            <p className="mt-1 break-words text-ink-soft">{asset.error}</p>
          </div>
        </div>
      )}

      <div className="grid gap-10 lg:grid-cols-[minmax(0,1fr)_340px]">
        <div className="min-w-0 space-y-10">
          {isPhoto ? (
            <PhotoPanel asset={asset} />
          ) : (
            <DocumentReader asset={asset} chunks={chunks} initialPage={initialPage} />
          )}
          {asset.children.length > 0 && (
            <section aria-labelledby="children">
              <h2 id="children" className="mb-3 text-xl font-semibold">
                Extracted from this item
              </h2>
              <AssetGrid assets={asset.children} />
            </section>
          )}
        </div>

        <aside className="space-y-6" aria-label="About this item">
          <Facts asset={asset} />
          <Provenance asset={asset} />
          <Location asset={asset} />
          <Entities entities={asset.entities} />
          <Pipeline asset={asset} />
        </aside>
      </div>
    </div>
  );
}

function captionLabel(source: string | null): { text: string; generated: boolean } {
  if (!source || source === "contributor") return { text: "Contributor’s caption", generated: false };
  if (source === "curator") return { text: "Curator’s caption", generated: false };
  return { text: `Generated by ${source}`, generated: true };
}

function PhotoPanel({ asset }: { asset: AssetDetail }) {
  const src = BROWSER_IMAGES.test(asset.mime) ? asset.original_url : asset.thumb_url;
  const label = captionLabel(asset.caption_source);
  return (
    <figure className="space-y-3">
      <div className="overflow-hidden rounded-[var(--radius-card)] bg-ink/90">
        {src ? (
          // eslint-disable-next-line @next/next/no-img-element -- archive originals are served by the API, not next/image
          <img
            src={src}
            alt={asset.caption ?? asset.title}
            width={asset.width ?? undefined}
            height={asset.height ?? undefined}
            className="mx-auto max-h-[75vh] w-auto object-contain"
          />
        ) : (
          <EmptyState title="Preview not available">The original file can still be downloaded.</EmptyState>
        )}
      </div>
      <figcaption className="space-y-2">
        {asset.caption ? (
          <>
            <p className="text-lg leading-relaxed">{asset.caption}</p>
            <p className="flex items-center gap-1.5 text-xs text-muted">
              {label.generated && <Sparkles aria-hidden className="size-3.5 text-indigo-ink" />}
              {label.text}
            </p>
          </>
        ) : (
          <p className="text-sm text-muted">
            {isBusy(asset) ? "A caption is being generated…" : "No caption yet."}
          </p>
        )}
        {asset.near_duplicate_of != null && (
          <p className="rounded-lg bg-ochre-soft px-3 py-2 text-sm">
            This photograph looks almost identical to{" "}
            <Link href={`/assets/${asset.near_duplicate_of}`} className="font-semibold underline">
              item #{asset.near_duplicate_of}
            </Link>
            .
          </p>
        )}
      </figcaption>
    </figure>
  );
}

function pageSource(page: PageOut): string {
  if (page.source === "native") return "Born-digital text";
  if (page.ocr_engine) {
    const conf = page.ocr_confidence != null ? ` · ${formatPercent(page.ocr_confidence)} confidence` : "";
    return `OCR by ${page.ocr_engine}${conf}`;
  }
  if (page.needs_ocr) return "Awaiting OCR";
  return titleCase(page.source);
}

function DocumentReader({ asset, chunks, initialPage }: { asset: AssetDetail; chunks: Chunk[]; initialPage: number }) {
  const passages = toPassages(chunks);
  const pageNos = asset.pages.length
    ? asset.pages.map((p) => p.page_no).sort((a, b) => a - b)
    : [...passages.keys()].sort((a, b) => a - b);
  const translatable = chunks.some((c) => c.translation);
  const [mode, setMode] = useState<Mode>(translatable ? "both" : "original");
  const [requested, setRequested] = useState(initialPage);
  const current = pageNos.includes(requested) ? requested : (pageNos[0] ?? 1);
  const index = pageNos.indexOf(current);
  const page = asset.pages.find((p) => p.page_no === current);
  const list = passages.get(current) ?? [];

  const go = (n: number) => {
    setRequested(n);
    const url = new URL(window.location.href);
    url.searchParams.set("page", String(n));
    url.hash = "";
    window.history.replaceState(null, "", url);
  };

  if (!pageNos.length) {
    return (
      <EmptyState title={isBusy(asset) ? "Reading this item…" : "No text was found"}>
        {isBusy(asset)
          ? "Text extraction, OCR and translation are running. This page updates by itself."
          : "Try reprocessing it, or check that the file contains pages."}
      </EmptyState>
    );
  }

  const effective: Mode = translatable ? mode : "original";
  const wide = !page?.image_url;

  return (
    <section aria-labelledby="reader-title">
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <h2 id="reader-title" className="text-xl font-semibold">
          {pageNos.length > 1 ? `Page ${current}` : "Text"}
          {pageNos.length > 1 && <span className="font-normal text-muted"> of {pageNos.length}</span>}
        </h2>
        {page && <span className="text-xs text-muted">{pageSource(page)}</span>}
        {translatable && (
          <div role="group" aria-label="Reading mode" className="ml-auto flex gap-1">
            {(
              [
                ["both", "Side by side"],
                ["original", "Original"],
                ["english", "English"],
              ] as const
            ).map(([value, label]) => (
              <button
                key={value}
                type="button"
                className="chip"
                aria-pressed={mode === value}
                onClick={() => setMode(value)}
              >
                {label}
              </button>
            ))}
          </div>
        )}
      </div>

      {pageNos.length > 1 && (
        <nav aria-label="Pages" className="mb-4 flex items-center gap-2">
          <button
            type="button"
            className="btn btn-secondary px-3"
            disabled={index <= 0}
            onClick={() => go(pageNos[index - 1])}
            aria-label="Previous page"
          >
            <ChevronLeft aria-hidden className="size-4" />
          </button>
          <label className="sr-only" htmlFor="page-select">
            Go to page
          </label>
          <select
            id="page-select"
            className="field w-auto py-1.5"
            value={current}
            onChange={(e) => go(Number(e.target.value))}
          >
            {pageNos.map((n) => (
              <option key={n} value={n}>
                Page {n}
              </option>
            ))}
          </select>
          <button
            type="button"
            className="btn btn-secondary px-3"
            disabled={index >= pageNos.length - 1}
            onClick={() => go(pageNos[index + 1])}
            aria-label="Next page"
          >
            <ChevronRight aria-hidden className="size-4" />
          </button>
        </nav>
      )}

      <div className={clsx("grid gap-6", !wide && "lg:grid-cols-[minmax(0,5fr)_minmax(0,6fr)]")}>
        {page?.image_url && (
          <a
            href={page.image_url}
            target="_blank"
            rel="noreferrer"
            className="block self-start overflow-hidden rounded-[var(--radius-card)] border border-sandstone bg-white lg:sticky lg:top-[76px]"
          >
            {/* eslint-disable-next-line @next/next/no-img-element -- rendered page images come from the API */}
            <img src={page.image_url} alt={`Scan of page ${current}`} className="w-full" />
            <span className="sr-only">(open full size in a new tab)</span>
          </a>
        )}
        <div className="min-w-0 space-y-3">
          {list.length ? (
            list.map((p) => (
              <PassageBlock key={p.chunk.id} passage={p} entities={asset.entities} mode={effective} wide={wide} />
            ))
          ) : (
            <EmptyState title={page?.needs_ocr ? "Waiting for OCR" : "No text on this page"}>
              {page?.needs_ocr
                ? "Handwriting recognition runs on a GPU worker; the text appears here once it finishes."
                : "This page has no readable text."}
            </EmptyState>
          )}
        </div>
      </div>
    </section>
  );
}

function PassageBlock({
  passage,
  entities,
  mode,
  wide,
}: {
  passage: Passage;
  entities: Entity[];
  mode: Mode;
  wide: boolean;
}) {
  const { chunk, body } = passage;
  const translation = chunk.translation;
  const showOriginal = mode !== "english" || !translation;
  const showEnglish = mode !== "original" && !!translation;
  const pieces = splitEntities(body, entitySpans(passage, entities));

  return (
    <article
      id={`passage-${chunk.id}`}
      className={clsx(
        "card grid scroll-mt-24 gap-4 p-4 target:ring-2 target:ring-ochre",
        showOriginal && showEnglish && wide && "md:grid-cols-2",
      )}
    >
      {showOriginal && (
        <p lang={langAttr(chunk.language)} className="text-[1.05rem] leading-loose whitespace-pre-line">
          {pieces.map((piece, i) =>
            piece.entity ? (
              <EntityMark key={i} entity={piece.entity}>
                {piece.text}
              </EntityMark>
            ) : (
              <span key={i}>{piece.text}</span>
            ),
          )}
        </p>
      )}
      {showEnglish && (
        <div className={clsx(showOriginal && "border-sandstone max-md:border-t max-md:pt-3 md:border-l md:pl-4")}>
          {showOriginal && (
            <p className="mb-1 text-xs font-semibold text-muted">
              English{chunk.translation_engine && <span className="font-normal"> · {chunk.translation_engine}</span>}
            </p>
          )}
          <p lang="en" className="leading-relaxed whitespace-pre-line text-ink-soft">
            {translation}
          </p>
        </div>
      )}
    </article>
  );
}

function entityTitle(e: Entity): string {
  const where = e.lat != null && e.lon != null ? ` (${e.lat.toFixed(3)}, ${e.lon.toFixed(3)})` : "";
  return `${titleCase(e.kind)}: ${e.normalized}${where}`;
}

function EntityMark({ entity, children }: { entity: Entity; children: string }) {
  return (
    <span
      title={entityTitle(entity)}
      className={clsx(
        "rounded-sm underline decoration-2 underline-offset-[6px]",
        entity.kind === "date" ? "decoration-ochre" : "decoration-indigo-ink/50",
      )}
    >
      {children}
    </span>
  );
}

function Card({ title, children, id }: { title: string; children: ReactNode; id: string }) {
  return (
    <section aria-labelledby={id} className="card p-4">
      <h2 id={id} className="mb-3 text-sm font-semibold tracking-wide text-muted uppercase">
        {title}
      </h2>
      {children}
    </section>
  );
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex justify-between gap-4 border-b border-sand py-1.5 text-sm last:border-0">
      <dt className="shrink-0 text-muted">{label}</dt>
      <dd className="min-w-0 text-right break-words">{children}</dd>
    </div>
  );
}

function Facts({ asset }: { asset: AssetDetail }) {
  return (
    <Card title="Details" id="facts">
      <dl>
        <Row label="Type">{kindLabel(asset.kind)}</Row>
        {asset.pages.length > 0 && <Row label="Pages">{formatNumber(asset.pages.length)}</Row>}
        {asset.width && asset.height && (
          <Row label="Dimensions">
            {asset.width} × {asset.height}px
          </Row>
        )}
        <Row label="File">
          <span className="break-all">{asset.original_filename}</span>
        </Row>
        <Row label="Format">{asset.mime}</Row>
        {asset.captured_at && <Row label="Captured">{formatDate(asset.captured_at)}</Row>}
        <Row label="Added">{formatDate(asset.created_at)}</Row>
        {asset.journey_slug && (
          <Row label="Journey">
            <Link href={`/journeys/${asset.journey_slug}`} className="text-indigo-ink underline">
              View expedition
            </Link>
          </Row>
        )}
        {asset.parent_id != null && (
          <Row label="Part of">
            <Link href={`/assets/${asset.parent_id}`} className="text-indigo-ink underline">
              Item #{asset.parent_id}
            </Link>
          </Row>
        )}
      </dl>
    </Card>
  );
}

function Provenance({ asset }: { asset: AssetDetail }) {
  if (!asset.contributor && !asset.license && !asset.attribution && !asset.source_url) return null;
  return (
    <Card title="Provenance" id="provenance">
      <dl>
        {asset.contributor && <Row label="Contributor">{asset.contributor}</Row>}
        {asset.license && <Row label="Licence">{asset.license}</Row>}
        {asset.source_url && (
          <Row label="Source">
            <a href={asset.source_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-indigo-ink underline">
              Original record <ExternalLink aria-hidden className="size-3" />
            </a>
          </Row>
        )}
      </dl>
      {asset.attribution && <p className="mt-2 text-xs leading-relaxed text-muted">{asset.attribution}</p>}
    </Card>
  );
}

const GEO_SOURCE: Record<string, string> = {
  exif: "From the photo’s GPS (EXIF)",
  manual: "Entered by the contributor",
  site: "From the linked heritage site",
  entity: "Inferred from places named in the text",
};

function Location({ asset }: { asset: AssetDetail }) {
  if (asset.lat == null || asset.lon == null) return null;
  const point: AssetsGeoJSON = {
    type: "FeatureCollection",
    features: [
      {
        type: "Feature",
        id: asset.id,
        geometry: { type: "Point", coordinates: [asset.lon, asset.lat] },
        properties: {
          id: asset.id,
          kind: asset.kind,
          title: asset.title,
          site_id: asset.site_id ?? null,
          geo_source: asset.geo_source,
          thumb_url: asset.thumb_url ?? null,
        },
      },
    ],
  };
  return (
    <Card title="Location" id="location">
      <AtlasMap
        label={`Map showing where “${asset.title}” was recorded`}
        assets={point}
        showAssets
        showSites={false}
        showRoutes={false}
        focus={{ kind: "point", lon: asset.lon, lat: asset.lat, zoom: 11 }}
        className="h-48 overflow-hidden rounded-lg"
      />
      <p className="mt-2 flex items-start gap-1.5 text-xs text-muted">
        <MapPin aria-hidden className="mt-px size-3.5 shrink-0" />
        <span>
          {asset.lat.toFixed(4)}, {asset.lon.toFixed(4)}
          {asset.geo_source && <> · {GEO_SOURCE[asset.geo_source] ?? asset.geo_source}</>}
        </span>
      </p>
    </Card>
  );
}

function Entities({ entities }: { entities: Entity[] }) {
  if (!entities.length) return null;
  const unique = new Map<string, Entity>();
  for (const e of entities) {
    const key = `${e.kind}:${e.normalized}`;
    if (!unique.has(key)) unique.set(key, e);
  }
  const groups = new Map<string, Entity[]>();
  for (const e of unique.values()) groups.set(e.kind, [...(groups.get(e.kind) ?? []), e]);
  return (
    <Card title="Mentioned in the text" id="entities">
      <dl className="space-y-3">
        {[...groups].map(([kind, list]) => (
          <div key={kind}>
            <dt className="mb-1 text-xs font-semibold text-muted">{titleCase(kind)}s</dt>
            <dd className="flex flex-wrap gap-1.5">
              {list.map((e) => (
                <Badge key={e.id} tone={kind === "date" ? "ochre" : "indigo"} title={`Written as “${e.surface}”`}>
                  {e.normalized}
                </Badge>
              ))}
            </dd>
          </div>
        ))}
      </dl>
    </Card>
  );
}

function Pipeline({ asset }: { asset: AssetDetail }) {
  const token = useIngestToken();
  const queryClient = useQueryClient();
  const refresh = () => queryClient.invalidateQueries({ queryKey: keys.asset(asset.id) });

  const reprocess = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST("/api/v1/assets/{asset_id}/reprocess", {
          params: { path: { asset_id: asset.id } },
          headers: authHeaders(token),
        }),
      ),
    onSuccess: refresh,
  });
  const retry = useMutation({
    mutationFn: (jobId: number) =>
      unwrap(
        api.POST("/api/v1/jobs/{job_id}/retry", { params: { path: { job_id: jobId } }, headers: authHeaders(token) }),
      ),
    onSuccess: refresh,
  });
  const authFailed = [reprocess.error, retry.error].some((e) => e instanceof ApiError && e.isAuth);
  const error = reprocess.error ?? retry.error;
  const stages = latestRuns(asset.jobs);

  return (
    <Card title="Processing pipeline" id="pipeline">
      {stages.length ? (
        <ol className="space-y-3">
          {stages.map(({ job, runs }) => (
            <JobRow
              key={job.id}
              job={job}
              runs={runs}
              onRetry={() => retry.mutate(job.id)}
              retrying={retry.isPending && retry.variables === job.id}
            />
          ))}
        </ol>
      ) : (
        <p className="text-sm text-muted">No jobs recorded.</p>
      )}
      <div className="mt-4 space-y-3 border-t border-sand pt-4">
        <button
          type="button"
          className="btn btn-secondary w-full"
          onClick={() => reprocess.mutate()}
          disabled={reprocess.isPending || isBusy(asset)}
        >
          <RefreshCw aria-hidden className={clsx("size-4", reprocess.isPending && "animate-spin")} />
          {isBusy(asset) ? "Processing…" : "Reprocess from scratch"}
        </button>
        <p aria-live="polite" className="text-xs text-danger empty:hidden">
          {error?.message}
        </p>
        <TokenField forceOpen={authFailed} />
      </div>
    </Card>
  );
}

function JobRow({ job, runs, onRetry, retrying }: { job: Job; runs: number; onRetry: () => void; retrying: boolean }) {
  const failed = job.status === "failed" || job.status === "dead";
  const duration = job.started_at ? formatDuration(job.started_at, job.finished_at) : null;
  return (
    <li className="text-sm">
      <div className="flex items-center gap-2">
        <StatusPill status={job.status} />
        <span className="min-w-0 flex-1 truncate font-medium" title={job.type}>
          {jobLabel(job.type)}
        </span>
        <span
          className="inline-flex items-center gap-0.5 text-xs text-muted"
          title={job.queue === "gpu" ? "Runs on a GPU worker (Colab)" : "Runs on the API server"}
        >
          {job.queue === "gpu" ? <Zap aria-hidden className="size-3" /> : <Cpu aria-hidden className="size-3" />}
          {job.queue.toUpperCase()}
        </span>
      </div>
      <p className="mt-0.5 pl-1 text-xs text-muted">
        {job.status === "queued" ? (
          <>
            Waiting since <RelativeTime iso={job.created_at} />
          </>
        ) : job.status === "leased" ? (
          `Running on ${job.lease_owner ?? "a worker"}`
        ) : (
          <>
            {duration && `took ${duration}`}
            {duration && job.finished_at && " · "}
            {job.finished_at && <RelativeTime iso={job.finished_at} />}
          </>
        )}
        {job.attempts > 1 && ` · attempt ${job.attempts}/${job.max_attempts}`}
        {runs > 1 && ` · ran ${runs} times`}
      </p>
      {failed && (
        <div className="mt-1 flex items-start gap-2 pl-1">
          {job.error && <p className="min-w-0 flex-1 text-xs break-words text-danger">{job.error}</p>}
          <button type="button" className="btn btn-ghost px-2 py-1 text-xs" onClick={onRetry} disabled={retrying}>
            <RotateCcw aria-hidden className="size-3" /> Retry
          </button>
        </div>
      )}
    </li>
  );
}
