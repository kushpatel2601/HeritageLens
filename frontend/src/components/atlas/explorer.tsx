"use client";

import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { ArrowRight, Box, Footprints, Images, Landmark, Layers, Route, Search, X } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";

import { AtlasMap, type MapFocus } from "@/components/map";
import { Badge, ErrorState, Skeleton } from "@/components/ui/primitives";
import { Thumb } from "@/components/ui/thumb";
import { assetsGeoQuery, journeysQuery, routesGeoQuery, sitesGeoQuery, sitesQuery } from "@/lib/api/queries";
import type { AssetFeatureProps, JourneyOut, SiteOut, SitesGeoJSON } from "@/lib/api/types";
import { categoryColor, formatEra, formatKm, kindLabel, scriptLang, titleCase } from "@/lib/format";

type Tab = "sites" | "journeys";

export function AtlasExplorer() {
  const sitesGeo = useQuery(sitesGeoQuery());
  const routesGeo = useQuery(routesGeoQuery());
  const assetsGeo = useQuery(assetsGeoQuery());
  const sites = useQuery(sitesQuery());
  const journeys = useQuery(journeysQuery());

  const [tab, setTab] = useState<Tab>("sites");
  const [layers, setLayers] = useState({ sites: true, routes: true, assets: false });
  const [category, setCategory] = useState<string | null>(null);
  const [filter, setFilter] = useState("");
  const [selectedSlug, setSelectedSlug] = useState<string | null>(null);
  const [selectedAsset, setSelectedAsset] = useState<AssetFeatureProps | null>(null);
  const [journeySlug, setJourneySlug] = useState<string | null>(null);
  const [focus, setFocus] = useState<MapFocus | null>(null);

  const categories = useMemo(() => {
    const counts = new Map<string, number>();
    for (const s of sites.data ?? []) counts.set(s.category, (counts.get(s.category) ?? 0) + 1);
    return [...counts.entries()].sort((a, b) => b[1] - a[1]);
  }, [sites.data]);

  const visibleSites = useMemo(() => {
    const raw = filter.trim();
    const needle = raw.toLocaleLowerCase();
    return (sites.data ?? []).filter(
      (s) =>
        (!category || s.category === category) &&
        (!needle ||
          s.name.toLocaleLowerCase().includes(needle) ||
          (s.name_native ?? "").includes(raw) ||
          (s.district ?? "").toLocaleLowerCase().includes(needle) ||
          s.tags.some((t) => t.toLocaleLowerCase().includes(needle))),
    );
  }, [sites.data, category, filter]);

  const mapSites = useMemo<SitesGeoJSON | undefined>(() => {
    if (!sitesGeo.data) return undefined;
    const keep = new Set(visibleSites.map((s) => s.id));
    return { ...sitesGeo.data, features: sitesGeo.data.features.filter((f) => keep.has(f.properties.id)) };
  }, [sitesGeo.data, visibleSites]);

  const selected = sites.data?.find((s) => s.slug === selectedSlug) ?? null;

  const selectSite = (site: SiteOut, fly: boolean) => {
    setSelectedSlug(site.slug);
    setSelectedAsset(null);
    if (fly) setFocus({ kind: "point", lon: site.lon, lat: site.lat, zoom: 13 });
  };

  const selectJourney = (j: JourneyOut) => {
    setJourneySlug(j.slug);
    setLayers((l) => ({ ...l, routes: true }));
    if (j.bbox?.length === 4) setFocus({ kind: "bounds", bbox: j.bbox as [number, number, number, number] });
  };

  return (
    <section aria-labelledby="atlas-heading" className="grid flex-1 grid-cols-[minmax(0,1fr)] lg:grid-cols-[400px_minmax(0,1fr)]">
      <h2 id="atlas-heading" className="sr-only">
        Interactive heritage atlas
      </h2>

      <div className="order-2 flex min-h-0 min-w-0 flex-col border-sandstone bg-parchment lg:order-1 lg:h-[calc(100dvh-60px)] lg:border-r">
        <div className="space-y-3 border-b border-sandstone p-4">
          <div role="group" aria-label="List" className="grid grid-cols-2 gap-1 rounded-full bg-sand p-1">
            {(["sites", "journeys"] as const).map((t) => (
              <button
                key={t}
                type="button"
                aria-pressed={tab === t}
                onClick={() => setTab(t)}
                className="flex items-center justify-center gap-1.5 rounded-full py-1.5 text-sm font-semibold text-ink-soft aria-pressed:bg-white aria-pressed:text-ink aria-pressed:shadow-sm"
              >
                {t === "sites" ? <Landmark aria-hidden className="size-4" /> : <Footprints aria-hidden className="size-4" />}
                {t === "sites" ? `Sites (${sites.data?.length ?? "…"})` : `Journeys (${journeys.data?.length ?? "…"})`}
              </button>
            ))}
          </div>

          <fieldset className="flex flex-wrap items-center gap-2 text-sm">
            <legend className="sr-only">Map layers</legend>
            <Layers aria-hidden className="size-4 text-muted" />
            <LayerToggle label="Sites" icon={Landmark} on={layers.sites} onChange={(v) => setLayers((l) => ({ ...l, sites: v }))} />
            <LayerToggle label="Routes" icon={Route} on={layers.routes} onChange={(v) => setLayers((l) => ({ ...l, routes: v }))} />
            <LayerToggle
              label="Archive items"
              icon={Images}
              on={layers.assets}
              onChange={(v) => setLayers((l) => ({ ...l, assets: v }))}
            />
          </fieldset>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto">
          {tab === "sites" ? (
            <SiteList
              loading={sites.isPending}
              error={sites.error}
              onRetry={() => void sites.refetch()}
              sites={visibleSites}
              total={sites.data?.length ?? 0}
              categories={categories}
              category={category}
              onCategory={setCategory}
              filter={filter}
              onFilter={setFilter}
              selectedSlug={selectedSlug}
              onSelect={(s) => selectSite(s, true)}
            />
          ) : (
            <JourneyList
              loading={journeys.isPending}
              error={journeys.error}
              onRetry={() => void journeys.refetch()}
              journeys={journeys.data ?? []}
              selectedSlug={journeySlug}
              onSelect={selectJourney}
            />
          )}
        </div>
      </div>

      <div className="relative order-1 h-[58vh] min-h-[360px] lg:order-2 lg:h-[calc(100dvh-60px)]">
        <AtlasMap
          label="Map of heritage sites, field-journey routes and geotagged archive items"
          className="size-full"
          sites={mapSites}
          routes={routesGeo.data}
          assets={assetsGeo.data}
          showSites={layers.sites}
          showRoutes={layers.routes}
          showAssets={layers.assets}
          selectedSiteId={selected?.id ?? null}
          highlightRoute={tab === "journeys" ? journeySlug : null}
          focus={focus}
          onSelectSite={(p) => {
            const site = sites.data?.find((s) => s.id === p.id);
            if (site) {
              setTab("sites");
              selectSite(site, false);
            }
          }}
          onSelectAsset={(a) => {
            setSelectedAsset(a);
            setSelectedSlug(null);
          }}
        />
        <div className="pointer-events-none absolute inset-x-3 bottom-3 flex justify-start sm:inset-x-4 sm:bottom-4">
          {selected && <SiteCard site={selected} onClose={() => setSelectedSlug(null)} />}
          {selectedAsset && <AssetCard asset={selectedAsset} onClose={() => setSelectedAsset(null)} />}
        </div>
        <Legend categories={categories.map(([c]) => c)} />
      </div>
    </section>
  );
}

function LayerToggle({
  label,
  icon: Icon,
  on,
  onChange,
}: {
  label: string;
  icon: typeof Landmark;
  on: boolean;
  onChange: (on: boolean) => void;
}) {
  return (
    <button type="button" aria-pressed={on} onClick={() => onChange(!on)} className="chip">
      <Icon aria-hidden className="size-3.5" />
      {label}
    </button>
  );
}

function SiteList(props: {
  loading: boolean;
  error: unknown;
  onRetry: () => void;
  sites: SiteOut[];
  total: number;
  categories: [string, number][];
  category: string | null;
  onCategory: (c: string | null) => void;
  filter: string;
  onFilter: (f: string) => void;
  selectedSlug: string | null;
  onSelect: (s: SiteOut) => void;
}) {
  if (props.error) return <ErrorState error={props.error} onRetry={props.onRetry} className="m-4" />;
  return (
    <div className="space-y-3 p-4">
      <div className="relative">
        <label htmlFor="site-filter" className="sr-only">
          Filter sites by name, district or tag
        </label>
        <Search aria-hidden className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted" />
        <input
          id="site-filter"
          type="search"
          value={props.filter}
          onChange={(e) => props.onFilter(e.target.value)}
          placeholder="Filter by name, district, tag…"
          className="field pl-9"
        />
      </div>
      <div role="group" aria-label="Filter by category" className="flex flex-wrap gap-1.5">
        <button type="button" className="chip" aria-pressed={props.category === null} onClick={() => props.onCategory(null)}>
          All
        </button>
        {props.categories.map(([c, n]) => (
          <button
            key={c}
            type="button"
            className="chip"
            aria-pressed={props.category === c}
            onClick={() => props.onCategory(props.category === c ? null : c)}
          >
            <span aria-hidden className="size-2 rounded-full" style={{ background: categoryColor(c) }} />
            {titleCase(c)} <span className="text-muted">{n}</span>
          </button>
        ))}
      </div>
      <p className="text-xs text-muted" aria-live="polite">
        {props.loading ? "Loading sites…" : `Showing ${props.sites.length} of ${props.total} sites`}
      </p>
      <ul className="space-y-2">
        {props.loading &&
          Array.from({ length: 5 }, (_, i) => (
            <li key={i}>
              <Skeleton className="h-20" />
            </li>
          ))}
        {props.sites.map((s) => (
          <li key={s.slug}>
            <button
              type="button"
              aria-pressed={props.selectedSlug === s.slug}
              onClick={() => props.onSelect(s)}
              className="flex w-full gap-3 rounded-xl border border-transparent p-2 text-left transition-colors hover:border-sandstone hover:bg-white aria-pressed:border-terracotta/40 aria-pressed:bg-white aria-pressed:shadow-sm"
            >
              <Thumb src={s.cover_url} alt="" className="size-16 shrink-0 rounded-lg" />
              <span className="min-w-0 flex-1">
                <span className="flex items-center gap-1.5">
                  <span aria-hidden className="size-2 shrink-0 rounded-full" style={{ background: categoryColor(s.category) }} />
                  <span className="truncate font-semibold">{s.name}</span>
                </span>
                {s.name_native && (
                  <span lang={scriptLang(s.name_native)} className="block truncate text-sm text-ink-soft">
                    {s.name_native}
                  </span>
                )}
                <span className="mt-0.5 block truncate text-xs text-muted">
                  {titleCase(s.category)} · {s.era_label ?? formatEra(s.era_start, s.era_end)}
                  {s.district ? ` · ${s.district}` : ""}
                </span>
              </span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

function JourneyList(props: {
  loading: boolean;
  error: unknown;
  onRetry: () => void;
  journeys: JourneyOut[];
  selectedSlug: string | null;
  onSelect: (j: JourneyOut) => void;
}) {
  if (props.error) return <ErrorState error={props.error} onRetry={props.onRetry} className="m-4" />;
  return (
    <ul className="space-y-3 p-4">
      {props.loading &&
        Array.from({ length: 3 }, (_, i) => (
          <li key={i}>
            <Skeleton className="h-32" />
          </li>
        ))}
      {props.journeys.map((j) => {
        const active = props.selectedSlug === j.slug;
        return (
          <li key={j.slug} className={clsx("card overflow-hidden", active && "ring-2 ring-terracotta/50")}>
            <button type="button" aria-pressed={active} onClick={() => props.onSelect(j)} className="block w-full p-4 text-left">
              <span className="flex items-center gap-2">
                <span aria-hidden className="h-1.5 w-8 rounded-full" style={{ background: j.color }} />
                <span className="text-xs font-semibold text-muted">
                  {j.year} · {j.fellow}
                </span>
              </span>
              <span className="mt-1 block font-serif text-xl leading-tight font-semibold">{j.title}</span>
              <span className="mt-1 line-clamp-2 block text-sm text-ink-soft">{j.summary}</span>
              <span className="mt-2 flex gap-3 text-xs text-muted">
                <span>{j.stop_count} stops</span>
                <span>{formatKm(j.distance_km)}</span>
                {j.region && <span>{j.region}</span>}
              </span>
            </button>
            <Link
              href={`/journeys/${j.slug}`}
              className="flex items-center justify-between border-t border-sandstone px-4 py-2 text-sm font-semibold text-indigo-ink hover:bg-sand"
            >
              Follow the journey in story mode <ArrowRight aria-hidden className="size-4" />
            </Link>
          </li>
        );
      })}
    </ul>
  );
}

function SiteCard({ site, onClose }: { site: SiteOut; onClose: () => void }) {
  return (
    <article
      aria-label={`Selected site: ${site.name}`}
      className="card pointer-events-auto flex w-full max-w-md gap-3 p-3 shadow-[var(--shadow-lift)]"
    >
      <Thumb src={site.cover_url} alt={site.name} className="size-24 shrink-0 rounded-lg" />
      <div className="min-w-0 flex-1">
        <div className="flex items-start gap-2">
          <h3 className="flex-1 font-serif text-xl leading-tight font-semibold">{site.name}</h3>
          <button type="button" onClick={onClose} className="-m-1 rounded p-1 text-muted hover:text-ink" aria-label="Close">
            <X aria-hidden className="size-4" />
          </button>
        </div>
        <p className="mt-0.5 line-clamp-2 text-sm text-ink-soft">{site.summary}</p>
        <div className="mt-2 flex flex-wrap items-center gap-1.5">
          {site.unesco && <Badge tone="ochre">UNESCO</Badge>}
          <Badge>{site.asset_count} items</Badge>
          {site.twin_count > 0 && (
            <Badge tone="indigo">
              <Box aria-hidden className="size-3" /> 3D twin
            </Badge>
          )}
          <Link href={`/sites/${site.slug}`} className="ml-auto text-sm font-semibold text-terracotta hover:underline">
            Open site →
          </Link>
        </div>
      </div>
    </article>
  );
}

function AssetCard({ asset, onClose }: { asset: AssetFeatureProps; onClose: () => void }) {
  return (
    <article
      aria-label={`Selected item: ${asset.title}`}
      className="card pointer-events-auto flex w-full max-w-sm gap-3 p-3 shadow-[var(--shadow-lift)]"
    >
      <Thumb src={asset.thumb_url} alt="" kind={asset.kind} className="size-20 shrink-0 rounded-lg" />
      <div className="min-w-0 flex-1">
        <div className="flex items-start gap-2">
          <h3 className="line-clamp-2 flex-1 font-semibold">{asset.title}</h3>
          <button type="button" onClick={onClose} className="-m-1 rounded p-1 text-muted hover:text-ink" aria-label="Close">
            <X aria-hidden className="size-4" />
          </button>
        </div>
        <p className="text-xs text-muted">
          {kindLabel(asset.kind)}
          {asset.geo_source && ` · located by ${asset.geo_source.replace(/_/g, " ")}`}
        </p>
        <Link href={`/assets/${asset.id}`} className="mt-1 inline-block text-sm font-semibold text-terracotta hover:underline">
          View item →
        </Link>
      </div>
    </article>
  );
}

function Legend({ categories }: { categories: string[] }) {
  if (!categories.length) return null;
  return (
    <details className="card absolute top-3 left-3 max-w-[220px] text-xs shadow-[var(--shadow-lift)]">
      <summary className="cursor-pointer px-3 py-2 font-semibold">Legend</summary>
      <ul className="space-y-1 px-3 pb-3">
        {categories.map((c) => (
          <li key={c} className="flex items-center gap-2">
            <span aria-hidden className="size-2.5 rounded-full border border-white" style={{ background: categoryColor(c) }} />
            {titleCase(c)}
          </li>
        ))}
        <li className="flex items-center gap-2">
          <span aria-hidden className="size-2.5 rounded-full border-2 border-amber-400 bg-white" />
          UNESCO World Heritage
        </li>
        <li className="flex items-center gap-2">
          <span aria-hidden className="h-0 w-4 border-t-2 border-dashed border-terracotta" />
          Field-journey route
        </li>
      </ul>
    </details>
  );
}
