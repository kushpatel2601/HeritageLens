"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { ChevronLeft, ChevronRight, Eye, Languages, MapPin, Search, Sparkles } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useState, type FormEvent } from "react";

import { Highlighted } from "@/components/search/highlighted";
import { Badge, EmptyState, ErrorState, LoadingBlock, Skeleton } from "@/components/ui/primitives";
import { KindIcon, Thumb } from "@/components/ui/thumb";
import { searchQuery } from "@/lib/api/queries";
import type { AssetKind, SearchHit, SearchParams, SearchResponse } from "@/lib/api/types";
import { categoryColor, kindLabel, langAttr, languageName, scriptLang, titleCase } from "@/lib/format";

const PAGE = 20;

const SCRIPTS: Record<string, string> = {
  Latn: "Latin",
  Gujr: "Gujarati",
  Deva: "Devanagari",
  Arab: "Perso-Arabic",
  Beng: "Bengali",
  Taml: "Tamil",
};

const MATCH_LABEL: Record<string, string> = {
  keyword: "Exact words",
  semantic: "Meaning",
  phonetic: "Sounds like",
  translation: "Translation",
  entity: "Place / date",
};

const EXAMPLES: { q: string; note: string }[] = [
  { q: "વાવ", note: "Gujarati script" },
  { q: "बावड़ी", note: "Hindi script" },
  { q: "vav", note: "romanised, matched by sound" },
  { q: "water temple for the sun", note: "by meaning" },
  { q: "1063", note: "a date in the notes" },
  { q: "double ikat weaving", note: "crafts" },
];

export function SearchView() {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();

  const q = params.get("q")?.trim() ?? "";
  const lang = params.get("lang") || undefined;
  const kind = params.get("kind") || undefined;
  const page = Math.max(1, Number(params.get("page")) || 1);

  const request: SearchParams = {
    q,
    lang,
    kind: kind ? [kind as AssetKind] : undefined,
    limit: PAGE,
    offset: (page - 1) * PAGE,
  };
  const { data, error, isFetching, isPending, refetch } = useQuery({
    ...searchQuery(request),
    placeholderData: keepPreviousData,
  });

  const update = (patch: Record<string, string | undefined>) => {
    const next = new URLSearchParams(params);
    for (const [k, v] of Object.entries(patch)) {
      if (v) next.set(k, v);
      else next.delete(k);
    }
    if (!("page" in patch)) next.delete("page");
    router.push(`${pathname}?${next.toString()}`, { scroll: "page" in patch });
  };

  return (
    <div className="mx-auto w-full max-w-7xl px-4 py-8">
      <h1 className="sr-only">Search the archive</h1>
      <SearchForm key={q} initial={q} onSubmit={(value) => update({ q: value, lang: undefined, kind: undefined })} />

      {!q ? (
        <Intro onPick={(value) => update({ q: value })} />
      ) : error ? (
        <ErrorState error={error} onRetry={() => void refetch()} className="mt-6" />
      ) : isPending ? (
        <LoadingBlock label="Searching text, translations and photographs…" />
      ) : data ? (
        <Results
          data={data}
          stale={isFetching}
          page={page}
          lang={lang}
          kind={kind}
          onFilter={(patch) => update(patch)}
          onPage={(p) => update({ page: p > 1 ? String(p) : undefined })}
          onSuggest={(s) => update({ q: s })}
        />
      ) : null}
    </div>
  );
}

function SearchForm({ initial, onSubmit }: { initial: string; onSubmit: (q: string) => void }) {
  const [value, setValue] = useState(initial);
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (value.trim()) onSubmit(value.trim());
  };
  return (
    <form role="search" onSubmit={submit} className="flex gap-2">
      <label htmlFor="q" className="sr-only">
        Search in any language or script
      </label>
      <div className="relative flex-1">
        <Search aria-hidden className="pointer-events-none absolute top-1/2 left-4 size-5 -translate-y-1/2 text-muted" />
        <input
          id="q"
          type="search"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          lang={scriptLang(value)}
          placeholder="Search in English, ગુજરાતી, हिन्दी, or romanised: “vav”, “kund”…"
          className="field py-3 pl-12 text-lg"
          autoComplete="off"
          enterKeyHint="search"
        />
      </div>
      <button type="submit" className="btn btn-primary px-6">
        Search
      </button>
    </form>
  );
}

function Intro({ onPick }: { onPick: (q: string) => void }) {
  return (
    <section className="mt-10 grid gap-8 lg:grid-cols-[1.2fr_1fr]">
      <div>
        <p className="eyebrow mb-2">Multilingual hybrid search</p>
        <h2 className="text-3xl font-semibold">Ask in any script. Find it in every script.</h2>
        <p className="mt-3 max-w-prose text-ink-soft">
          Every page of every notebook has been read by OCR, split into passages and translated. A query is matched
          four ways at once: the exact words, how they sound across scripts (so <em>vav</em> finds <span lang="gu">વાવ</span>),
          their meaning through multilingual embeddings, and the places and dates extracted from the text. Photographs
          are matched by what they show.
        </p>
      </div>
      <div>
        <h3 className="mb-3 text-lg font-semibold">Try one of these</h3>
        <ul className="flex flex-wrap gap-2">
          {EXAMPLES.map((ex) => (
            <li key={ex.q}>
              <button type="button" className="chip py-1.5" onClick={() => onPick(ex.q)}>
                <span lang={scriptLang(ex.q)} className="font-semibold text-ink">
                  {ex.q}
                </span>
                <span className="text-muted">· {ex.note}</span>
              </button>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

function Results({
  data,
  stale,
  page,
  lang,
  kind,
  onFilter,
  onPage,
  onSuggest,
}: {
  data: SearchResponse;
  stale: boolean;
  page: number;
  lang?: string;
  kind?: string;
  onFilter: (patch: Record<string, string | undefined>) => void;
  onPage: (page: number) => void;
  onSuggest: (q: string) => void;
}) {
  const pages = Math.max(1, Math.ceil(data.total / PAGE));
  const { interpreted } = data;
  const kinds = Object.entries(data.facets.kind ?? {}).sort((a, b) => b[1] - a[1]);
  const langs = Object.entries(data.facets.language ?? {}).sort((a, b) => b[1] - a[1]);

  return (
    <div className={clsx("mt-6 transition-opacity", stale && "opacity-60")} aria-busy={stale}>
      <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-muted" aria-live="polite">
        <span>
          <strong className="text-ink">{data.total}</strong> {data.total === 1 ? "passage" : "passages"} for “
          <span lang={scriptLang(data.query)}>{data.query}</span>”
        </span>
        {interpreted.script && <Badge>{SCRIPTS[interpreted.script] ?? interpreted.script} script</Badge>}
        {interpreted.language && <Badge>{languageName(interpreted.language)}</Badge>}
        {interpreted.phonetic && (
          <Badge tone="indigo" title="Script-independent phonetic key used to match transliterations">
            sounds like “{interpreted.phonetic}”
          </Badge>
        )}
        <span className="ml-auto text-xs">
          {Math.round(data.took_ms)} ms · {data.backend}
        </span>
      </p>

      {data.suggestions.length > 0 && (
        <p className="mt-3 text-sm">
          Did you mean{" "}
          {data.suggestions.map((s, i) => (
            <span key={s}>
              {i > 0 && ", "}
              <button type="button" className="font-semibold text-terracotta underline" onClick={() => onSuggest(s)}>
                <span lang={scriptLang(s)}>{s}</span>
              </button>
            </span>
          ))}
          ?
        </p>
      )}

      <div className="mt-6 grid gap-8 lg:grid-cols-[220px_1fr]">
        <aside aria-label="Refine results" className="space-y-6">
          <Facet
            title="Type"
            options={kinds.map(([k, n]) => ({ value: k, label: kindLabel(k), count: n }))}
            value={kind}
            onChange={(v) => onFilter({ kind: v, lang })}
          />
          <Facet
            title="Language"
            options={langs.map(([l, n]) => ({ value: l, label: l === "und" ? "Undetermined" : languageName(l), count: n }))}
            value={lang}
            onChange={(v) => onFilter({ lang: v, kind })}
          />
        </aside>

        <div className="min-w-0 space-y-8">
          {page === 1 && data.sites.length > 0 && (
            <section aria-labelledby="site-hits">
              <h2 id="site-hits" className="mb-3 text-xl font-semibold">
                Sites
              </h2>
              <ul className="flex gap-3 overflow-x-auto pb-1">
                {data.sites.map((s) => (
                  <li key={s.slug} className="shrink-0">
                    <Link
                      href={`/sites/${s.slug}`}
                      className="card flex w-64 items-start gap-2 p-3 transition-shadow hover:shadow-[var(--shadow-lift)]"
                    >
                      <MapPin aria-hidden className="mt-0.5 size-4 shrink-0" style={{ color: categoryColor(s.category) }} />
                      <span className="min-w-0">
                        <span className="block truncate font-semibold">{s.name}</span>
                        {s.name_native && (
                          <span lang={scriptLang(s.name_native)} className="block truncate text-sm text-ink-soft">
                            {s.name_native}
                          </span>
                        )}
                        <span className="text-xs text-muted">
                          {titleCase(s.category)} · matched by {s.reason.replace(/_/g, " ")}
                        </span>
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            </section>
          )}

          <section aria-labelledby="text-hits">
            <h2 id="text-hits" className="mb-3 text-xl font-semibold">
              Passages in notes, journals and documents
            </h2>
            {data.hits.length ? (
              <ol className="space-y-4" start={(page - 1) * PAGE + 1}>
                {data.hits.map((hit) => (
                  <li key={hit.chunk_id}>
                    <HitCard hit={hit} />
                  </li>
                ))}
              </ol>
            ) : (
              <EmptyState title="No matching passages">
                Try another spelling, a different script, or remove a filter.
              </EmptyState>
            )}
            {pages > 1 && (
              <nav aria-label="Result pages" className="mt-6 flex items-center justify-between gap-3">
                <button type="button" className="btn btn-secondary" disabled={page <= 1} onClick={() => onPage(page - 1)}>
                  <ChevronLeft aria-hidden className="size-4" /> Previous
                </button>
                <span className="text-sm text-muted">
                  Page {page} of {pages}
                </span>
                <button
                  type="button"
                  className="btn btn-secondary"
                  disabled={page >= pages}
                  onClick={() => onPage(page + 1)}
                >
                  Next <ChevronRight aria-hidden className="size-4" />
                </button>
              </nav>
            )}
          </section>

          {page === 1 && data.photos.length > 0 && (
            <section aria-labelledby="photo-hits">
              <h2 id="photo-hits" className="mb-1 flex items-center gap-2 text-xl font-semibold">
                <Eye aria-hidden className="size-5 text-terracotta" /> Photographs that show this
              </h2>
              <p className="mb-3 text-sm text-muted">Matched on image content, not captions.</p>
              <ul className="grid grid-cols-3 gap-2 sm:grid-cols-4 lg:grid-cols-6">
                {data.photos.map(({ asset, score }) => (
                  <li key={asset.id}>
                    <Link href={`/assets/${asset.id}`} className="group block" title={`${asset.title} (similarity ${score.toFixed(2)})`}>
                      <Thumb
                        src={asset.thumb_url}
                        alt={asset.title}
                        className="aspect-square w-full rounded-lg transition-opacity group-hover:opacity-85"
                      />
                    </Link>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </div>
      </div>
    </div>
  );
}

function Facet({
  title,
  options,
  value,
  onChange,
}: {
  title: string;
  options: { value: string; label: string; count: number }[];
  value?: string;
  onChange: (value: string | undefined) => void;
}) {
  if (!options.length && !value) return null;
  return (
    <div role="group" aria-label={`Filter by ${title.toLowerCase()}`}>
      <h3 className="mb-2 text-xs font-semibold tracking-wide text-muted uppercase">{title}</h3>
      <ul className="flex flex-wrap gap-1.5 lg:flex-col lg:items-stretch">
        {value && !options.some((o) => o.value === value) && (
          <li>
            <button type="button" className="chip w-full justify-between" aria-pressed onClick={() => onChange(undefined)}>
              {value} <span>×</span>
            </button>
          </li>
        )}
        {options.map((o) => (
          <li key={o.value}>
            <button
              type="button"
              className="chip w-full justify-between"
              aria-pressed={value === o.value}
              onClick={() => onChange(value === o.value ? undefined : o.value)}
            >
              <span>{o.label}</span>
              <span className="text-muted tabular-nums">{o.count}</span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

function HitCard({ hit }: { hit: SearchHit }) {
  const { asset } = hit;
  return (
    <article className="card flex gap-4 p-4">
      <Link href={`/assets/${asset.id}`} tabIndex={-1} aria-hidden className="hidden shrink-0 sm:block">
        <Thumb src={asset.thumb_url} alt="" kind={asset.kind} className="size-24 rounded-lg" />
      </Link>
      <div className="min-w-0 flex-1">
        <h3 className="font-semibold">
          <Link
            href={`/assets/${asset.id}?page=${hit.page_no}#passage-${hit.chunk_id}`}
            className="hover:underline"
            lang={langAttr(asset.language)}
          >
            {asset.title}
          </Link>
        </h3>
        <p className="mt-0.5 flex flex-wrap items-center gap-x-2 text-xs text-muted">
          <KindIcon kind={asset.kind} className="size-3.5" />
          {kindLabel(asset.kind)}
          {hit.page_no > 0 && <span>· page {hit.page_no}</span>}
          {asset.site_name && <span>· {asset.site_name}</span>}
          {hit.language && <span>· {languageName(hit.language)}</span>}
        </p>
        <Highlighted snippet={hit.snippet} lang={langAttr(hit.language)} className="mt-2 leading-relaxed" />
        {hit.translation && (
          <div className="mt-2 rounded-lg bg-sand/70 p-3 text-sm">
            <p className="mb-1 flex items-center gap-1 text-xs font-semibold text-muted">
              <Languages aria-hidden className="size-3.5" /> English translation
              {hit.translation_engine && <span className="font-normal">· {hit.translation_engine}</span>}
            </p>
            <Highlighted snippet={hit.translation} lang="en" className="text-ink-soft" />
          </div>
        )}
        <div className="mt-2 flex flex-wrap items-center gap-1.5">
          {hit.matched_by.map((m) => (
            <Badge key={m} tone={m === "semantic" ? "indigo" : m === "phonetic" ? "ochre" : "neutral"}>
              {m === "semantic" && <Sparkles aria-hidden className="size-3" />}
              {MATCH_LABEL[m] ?? titleCase(m)}
            </Badge>
          ))}
          {hit.more_in_asset > 0 && (
            <span className="text-xs text-muted">
              +{hit.more_in_asset} more {hit.more_in_asset === 1 ? "passage" : "passages"} in this item
            </span>
          )}
        </div>
      </div>
    </article>
  );
}

export function SearchSkeleton() {
  return (
    <div className="mx-auto w-full max-w-7xl space-y-4 px-4 py-8" aria-hidden>
      <Skeleton className="h-14" />
      <Skeleton className="h-6 w-1/2" />
      <Skeleton className="h-40" />
      <Skeleton className="h-40" />
    </div>
  );
}
