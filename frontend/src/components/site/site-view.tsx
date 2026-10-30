"use client";

import { useQuery } from "@tanstack/react-query";
import { Box, Info, MapPin, Search } from "lucide-react";
import Link from "next/link";
import { useState, type ReactNode } from "react";

import { AssetGrid } from "@/components/asset-grid";
import { TwinBuilder } from "@/components/site/twin-builder";
import { Badge, EmptyState, SectionHeading } from "@/components/ui/primitives";
import { Thumb } from "@/components/ui/thumb";
import { TwinViewer } from "@/components/viewer";
import { siteQuery } from "@/lib/api/queries";
import type { SiteDetail, Twin } from "@/lib/api/types";
import {
  categoryColor,
  formatEra,
  formatKm,
  formatNumber,
  langAttr,
  languageName,
  languageNative,
  scriptLang,
  titleCase,
} from "@/lib/format";

const METHOD_LABEL: Record<string, string> = {
  "depth-relief": "Depth relief",
  "gaussian-splat": "Gaussian splat",
  procedural: "Procedural typology",
};

export function SiteView({ initial }: { initial: SiteDetail }) {
  const { data: site } = useQuery({ ...siteQuery(initial.slug), initialData: initial });
  const photos = site.assets.filter((a) => (a.kind === "photo" || a.kind === "scan") && a.status === "ready");

  return (
    <article>
      <header className="relative isolate overflow-hidden bg-ink text-white">
        {site.cover_url && (
          <Thumb
            src={site.cover_url}
            alt=""
            eager
            className="absolute inset-0 -z-10 size-full opacity-55"
          />
        )}
        <div className="absolute inset-0 -z-10 bg-gradient-to-t from-ink via-ink/60 to-ink/10" />
        <div className="mx-auto max-w-7xl px-4 pt-24 pb-8 sm:pt-32">
          <nav aria-label="Breadcrumb" className="mb-3 text-sm text-white/75">
            <Link href="/sites" className="hover:text-white hover:underline">
              Sites
            </Link>{" "}
            / <span aria-current="page">{site.name}</span>
          </nav>
          <div className="flex flex-wrap items-center gap-2">
            <Badge className="border-white/20 bg-white/15 text-white">
              <span aria-hidden className="size-2 rounded-full" style={{ background: categoryColor(site.category) }} />
              {titleCase(site.category)}
            </Badge>
            {site.unesco && <Badge tone="ochre">UNESCO World Heritage</Badge>}
            {site.twin_count > 0 && (
              <Badge tone="indigo">
                <Box aria-hidden className="size-3" /> 3D twin
              </Badge>
            )}
          </div>
          <h1 className="mt-2 text-5xl font-semibold sm:text-6xl">{site.name}</h1>
          {site.name_native && (
            <p lang={scriptLang(site.name_native)} className="mt-1 text-2xl text-white/85">
              {site.name_native}
            </p>
          )}
          <p className="mt-3 max-w-3xl text-lg text-white/85">{site.summary}</p>
          <p className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-white/75">
            <span className="flex items-center gap-1">
              <MapPin aria-hidden className="size-4" />
              {[site.district, site.state].filter(Boolean).join(", ") || "India"}
            </span>
            <span>{site.era_label ?? formatEra(site.era_start, site.era_end)}</span>
          </p>
        </div>
      </header>

      <div className="mx-auto grid max-w-7xl gap-10 px-4 py-10 lg:grid-cols-[1fr_320px]">
        <div className="min-w-0 space-y-12">
          {site.description && (
            <section aria-labelledby="about">
              <SectionHeading id="about" eyebrow="About" title="The site" />
              <div className="max-w-prose space-y-3 text-lg leading-relaxed text-ink-soft">
                {site.description.split(/\n{2,}/).map((p, i) => (
                  <p key={i}>{p}</p>
                ))}
              </div>
            </section>
          )}

          <TwinSection twins={site.twins} />

          <section aria-labelledby="items">
            <SectionHeading id="items" eyebrow="Archive" title={`Field material (${site.assets.length})`}>
              <Link href={`/search?q=${encodeURIComponent(site.name)}`} className="btn btn-secondary">
                <Search aria-hidden className="size-4" /> Search mentions
              </Link>
            </SectionHeading>
            {site.assets.length ? (
              <AssetGrid assets={site.assets} />
            ) : (
              <EmptyState title="No material yet">
                <Link href="/contribute" className="font-semibold text-terracotta underline">
                  Contribute photographs or notes
                </Link>{" "}
                for this site.
              </EmptyState>
            )}
          </section>

          <section aria-labelledby="build" className="card p-5">
            <h2 id="build" className="mb-3 text-2xl font-semibold">
              Build a digital twin
            </h2>
            <TwinBuilder slug={site.slug} photos={photos} />
          </section>
        </div>

        <aside className="space-y-6" aria-label="Site facts">
          <section className="card p-5">
            <h2 className="mb-3 text-xl font-semibold">At a glance</h2>
            <dl className="space-y-3 text-sm">
              <Fact label="Period">
                {formatEra(site.era_start, site.era_end)}
                {site.era_label && <span className="block text-muted">{site.era_label}</span>}
              </Fact>
              <EraBar start={site.era_start} end={site.era_end} />
              <Fact label="Location">
                {[site.district, site.state].filter(Boolean).join(", ")}
                <span className="block font-mono text-xs text-muted">
                  {site.lat.toFixed(4)}°N, {site.lon.toFixed(4)}°E
                </span>
              </Fact>
              {site.alt_names.length > 0 && (
                <Fact label="Also known as">
                  <ul>
                    {site.alt_names.map((n) => (
                      <li key={n} lang={scriptLang(n)}>
                        {n}
                      </li>
                    ))}
                  </ul>
                </Fact>
              )}
              {Object.keys(site.languages).length > 0 && (
                <Fact label="Languages in the archive">
                  <ul className="mt-1 flex flex-wrap gap-1.5">
                    {Object.entries(site.languages).map(([code, n]) => (
                      <li key={code}>
                        <Badge title={languageName(code)}>
                          <span lang={langAttr(code)}>{languageNative(code) ?? code}</span>
                          <span className="text-muted">{formatNumber(n)}</span>
                        </Badge>
                      </li>
                    ))}
                  </ul>
                </Fact>
              )}
              {site.tags.length > 0 && (
                <Fact label="Tags">
                  <span className="flex flex-wrap gap-1">
                    {site.tags.map((t) => (
                      <Badge key={t}>{t}</Badge>
                    ))}
                  </span>
                </Fact>
              )}
            </dl>
          </section>

          {site.journeys.length > 0 && (
            <section className="card p-5">
              <h2 className="mb-3 text-xl font-semibold">On these journeys</h2>
              <ul className="space-y-2">
                {site.journeys.map((j) => (
                  <li key={j.slug}>
                    <Link href={`/journeys/${j.slug}`} className="flex items-center gap-2 font-semibold hover:underline">
                      <span aria-hidden className="h-1.5 w-6 shrink-0 rounded-full" style={{ background: j.color }} />
                      {j.title} <span className="font-normal text-muted">({j.year})</span>
                    </Link>
                  </li>
                ))}
              </ul>
            </section>
          )}

          {site.nearby.length > 0 && (
            <section className="card p-5">
              <h2 className="mb-3 text-xl font-semibold">Nearby</h2>
              <ul className="space-y-2 text-sm">
                {site.nearby.map((n) => (
                  <li key={n.slug} className="flex items-center gap-2">
                    <span aria-hidden className="size-2 rounded-full" style={{ background: categoryColor(n.category) }} />
                    <Link href={`/sites/${n.slug}`} className="flex-1 font-semibold hover:underline">
                      {n.name}
                    </Link>
                    <span className="text-muted tabular-nums">{formatKm(n.distance_km)}</span>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </aside>
      </div>
    </article>
  );
}

function TwinSection({ twins }: { twins: Twin[] }) {
  const [activeId, setActiveId] = useState<number | null>(null);
  const twin = twins.find((t) => t.id === activeId) ?? twins[0];
  if (!twin) return null;
  const note = typeof twin.meta.note === "string" ? twin.meta.note : null;
  return (
    <section aria-labelledby="twin">
      <SectionHeading id="twin" eyebrow="Digital twin" title={twin.title}>
        {twins.length > 1 && (
          <div role="group" aria-label="Choose model" className="flex flex-wrap gap-1.5">
            {twins.map((t, i) => (
              <button
                key={t.id}
                type="button"
                className="chip"
                aria-pressed={t.id === twin.id}
                onClick={() => setActiveId(t.id)}
              >
                Model {i + 1}
              </button>
            ))}
          </div>
        )}
      </SectionHeading>
      <TwinViewer key={twin.id} twin={twin} />
      <div className="mt-3 flex flex-wrap items-center gap-2 text-sm text-ink-soft">
        <Badge tone="indigo">{METHOD_LABEL[twin.method] ?? titleCase(twin.method)}</Badge>
        {twin.point_count != null && <Badge>{formatNumber(twin.point_count)} points</Badge>}
        {twin.source_asset_ids.length > 0 && <Badge>from {twin.source_asset_ids.length} photographs</Badge>}
      </div>
      {note && (
        <p className="mt-3 flex gap-2 rounded-lg border border-ochre/30 bg-ochre-soft/60 p-3 text-sm">
          <Info aria-hidden className="mt-0.5 size-4 shrink-0 text-ochre" />
          {note}
        </p>
      )}
    </section>
  );
}

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <dt className="text-xs font-semibold tracking-wide text-muted uppercase">{label}</dt>
      <dd className="mt-0.5">{children}</dd>
    </div>
  );
}

const TIMELINE = { from: -3000, to: 2000 };

/** Where the site sits on a 5,000-year axis (Harappan to present) — gives undated visitors scale. */
function EraBar({ start, end }: { start: number | null; end: number | null }) {
  if (start == null && end == null) return null;
  const span = TIMELINE.to - TIMELINE.from;
  const pct = (y: number) => Math.min(100, Math.max(0, ((y - TIMELINE.from) / span) * 100));
  const a = pct(start ?? end!);
  const b = pct(end ?? start!);
  return (
    <div aria-hidden className="pt-1 pb-4">
      <div className="relative h-2 rounded-full bg-sand">
        <div
          className="absolute inset-y-0 rounded-full bg-terracotta"
          style={{ left: `${a}%`, width: `${Math.max(1.2, b - a)}%` }}
        />
        <span className="absolute top-3 left-0 text-[10px] text-muted">3000 BCE</span>
        <span className="absolute top-3 left-[60%] -translate-x-1/2 text-[10px] text-muted">0</span>
        <span className="absolute top-3 right-0 text-[10px] text-muted">2000 CE</span>
      </div>
    </div>
  );
}
