"use client";

import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { ChevronLeft, ChevronRight, Search } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useRef, useState, type ReactNode } from "react";

import { AssetGrid } from "@/components/asset-grid";
import { EmptyState, ErrorState, LoadingBlock, Skeleton } from "@/components/ui/primitives";
import { assetListQuery, sitesQuery, statsQuery } from "@/lib/api/queries";
import type { AssetKind, AssetListParams, AssetStatus } from "@/lib/api/types";
import { KIND_LABELS, formatNumber, languageName } from "@/lib/format";

const LIMIT = 48;
const KINDS = Object.keys(KIND_LABELS) as AssetKind[];
const STATUSES: AssetStatus[] = ["ready", "processing", "queued", "failed"];
const SORTS = [
  { value: "recent", label: "Recently added" },
  { value: "title", label: "Title A–Z" },
  { value: "era", label: "Oldest era first" },
] as const;

type Sort = (typeof SORTS)[number]["value"];

export function ArchiveBrowser() {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const sites = useQuery(sitesQuery());
  const stats = useQuery(statsQuery());
  const [inputKey, setInputKey] = useState(0);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const kind = params.get("kind") ?? "";
  const status = params.get("status") ?? "";
  const language = params.get("language") ?? "";
  const site = params.get("site") ?? "";
  const sort = (SORTS.some((s) => s.value === params.get("sort")) ? params.get("sort") : "recent") as Sort;
  const q = params.get("q") ?? "";
  const page = Math.max(1, Number(params.get("page")) || 1);

  const request: AssetListParams = {
    kind: kind ? [kind as AssetKind] : undefined,
    status: (status || undefined) as AssetStatus | undefined,
    language: language || undefined,
    site_id: site ? Number(site) : undefined,
    q: q || undefined,
    sort,
    limit: LIMIT,
    offset: (page - 1) * LIMIT,
  };
  const { data, error, isPending, isFetching, refetch } = useQuery(assetListQuery(request));

  const update = (patch: Record<string, string | undefined>) => {
    const next = new URLSearchParams(params);
    for (const [k, v] of Object.entries(patch)) {
      if (v) next.set(k, v);
      else next.delete(k);
    }
    if (!("page" in patch)) next.delete("page");
    const qs = next.toString();
    router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: "page" in patch });
  };

  const onTitle = (value: string) => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => update({ q: value.trim() || undefined }), 350);
  };

  const filtered = Boolean(kind || status || language || site || q);
  const clear = () => {
    setInputKey((k) => k + 1);
    router.replace(pathname);
  };
  const pages = data ? Math.max(1, Math.ceil(data.total / LIMIT)) : 1;
  const languages = Object.keys(stats.data?.languages ?? {}).sort();

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4">
        <div role="group" aria-label="Filter by type" className="flex flex-wrap gap-1.5">
          <button type="button" className="chip" aria-pressed={!kind} onClick={() => update({ kind: undefined })}>
            All types
          </button>
          {KINDS.map((k) => (
            <button
              key={k}
              type="button"
              className="chip"
              aria-pressed={kind === k}
              onClick={() => update({ kind: kind === k ? undefined : k })}
            >
              {KIND_LABELS[k]}
              {stats.data?.assets_by_kind[k] != null && (
                <span className="text-xs opacity-70 tabular-nums">{stats.data.assets_by_kind[k]}</span>
              )}
            </button>
          ))}
        </div>

        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-[2fr_1fr_1fr_1fr_1fr]">
          <div className="relative">
            <label htmlFor="archive-q" className="sr-only">
              Filter by title
            </label>
            <Search aria-hidden className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted" />
            <input
              key={inputKey}
              id="archive-q"
              type="search"
              defaultValue={q}
              onChange={(e) => onTitle(e.target.value)}
              placeholder="Title contains…"
              className="field pl-9"
            />
          </div>
          <Select label="Site" value={site} onChange={(v) => update({ site: v })}>
            <option value="">All sites</option>
            {sites.data?.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </Select>
          <Select label="Language" value={language} onChange={(v) => update({ language: v })}>
            <option value="">Any language</option>
            {languages.map((l) => (
              <option key={l} value={l}>
                {languageName(l)}
              </option>
            ))}
          </Select>
          <Select label="Status" value={status} onChange={(v) => update({ status: v })}>
            <option value="">Any status</option>
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {s[0].toUpperCase() + s.slice(1)}
              </option>
            ))}
          </Select>
          <Select label="Sort" value={sort} onChange={(v) => update({ sort: v === "recent" ? undefined : v })}>
            {SORTS.map((s) => (
              <option key={s.value} value={s.value}>
                {s.label}
              </option>
            ))}
          </Select>
        </div>
      </div>

      <p className="flex items-center gap-3 text-sm text-muted" aria-live="polite">
        {data && (
          <span>
            <strong className="text-ink">{formatNumber(data.total)}</strong> {data.total === 1 ? "item" : "items"}
            {pages > 1 && ` · page ${page} of ${pages}`}
          </span>
        )}
        {filtered && (
          <button type="button" className="font-semibold text-terracotta underline" onClick={clear}>
            Clear filters
          </button>
        )}
      </p>

      {error ? (
        <ErrorState error={error} onRetry={() => void refetch()} />
      ) : isPending ? (
        <LoadingBlock label="Loading the collection…" />
      ) : data.items.length ? (
        <div className={clsx("transition-opacity", isFetching && "opacity-60")} aria-busy={isFetching}>
          <AssetGrid assets={data.items} />
        </div>
      ) : (
        <EmptyState title="Nothing matches these filters">Try removing a filter, or contribute new material.</EmptyState>
      )}

      {pages > 1 && (
        <nav aria-label="Pages" className="flex items-center justify-between gap-3">
          <button
            type="button"
            className="btn btn-secondary"
            disabled={page <= 1}
            onClick={() => update({ page: page > 2 ? String(page - 1) : undefined })}
          >
            <ChevronLeft aria-hidden className="size-4" /> Previous
          </button>
          <button
            type="button"
            className="btn btn-secondary"
            disabled={page >= pages}
            onClick={() => update({ page: String(page + 1) })}
          >
            Next <ChevronRight aria-hidden className="size-4" />
          </button>
        </nav>
      )}
    </div>
  );
}

function Select({
  label,
  value,
  onChange,
  children,
}: {
  label: string;
  value: string;
  onChange: (value: string | undefined) => void;
  children: ReactNode;
}) {
  return (
    <label className="block">
      <span className="sr-only">{label}</span>
      <select className="field" value={value} onChange={(e) => onChange(e.target.value || undefined)}>
        {children}
      </select>
    </label>
  );
}

export function ArchiveSkeleton() {
  return (
    <div className="space-y-6" aria-hidden>
      <Skeleton className="h-9 w-2/3" />
      <Skeleton className="h-11" />
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
        {Array.from({ length: 8 }, (_, i) => (
          <Skeleton key={i} className="aspect-[4/3]" />
        ))}
      </div>
    </div>
  );
}
