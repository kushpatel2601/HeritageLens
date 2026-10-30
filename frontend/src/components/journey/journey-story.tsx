"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, CalendarDays, Footprints, MapPin, Route } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";

import { AtlasMap, type MapFocus, type StopMarker } from "@/components/map";
import { Thumb } from "@/components/ui/thumb";
import { journeyQuery } from "@/lib/api/queries";
import type { JourneyDetail, RoutesGeoJSON } from "@/lib/api/types";
import { formatDate, formatKm, kindLabel, scriptLang } from "@/lib/format";

/**
 * Story mode: the narrative scrolls on the left while the map follows. The stop crossing the
 * middle of the viewport becomes active (IntersectionObserver); prev/next buttons and the
 * arrow keys move between stops and move focus to the stop heading for screen-reader users.
 */
export function JourneyStory({ initial }: { initial: JourneyDetail }) {
  const { data: journey } = useQuery({ ...journeyQuery(initial.slug), initialData: initial });
  const [active, setActive] = useState<number | null>(null);
  const sectionRefs = useRef<(HTMLElement | null)[]>([]);
  const count = journey.stops.length;

  const markers = useMemo<StopMarker[]>(
    () => journey.stops.map((s, i) => ({ seq: i + 1, title: s.title, lat: s.lat, lon: s.lon })),
    [journey.stops],
  );

  const routes = useMemo<RoutesGeoJSON>(
    () => ({
      type: "FeatureCollection",
      features: [
        {
          type: "Feature",
          geometry: (journey.route as { geometry: RoutesGeoJSON["features"][number]["geometry"] }).geometry,
          properties: { slug: journey.slug, title: journey.title, color: journey.color, year: journey.year },
        },
      ],
    }),
    [journey],
  );

  const focus = useMemo<MapFocus | null>(() => {
    const stop = active == null ? null : journey.stops[active - 1];
    if (stop) return { kind: "point", lon: stop.lon, lat: stop.lat, zoom: 12 };
    if (journey.bbox?.length === 4) return { kind: "bounds", bbox: journey.bbox as [number, number, number, number], padding: 80 };
    return null;
  }, [active, journey]);

  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (!entry.isIntersecting) continue;
          const n = Number((entry.target as HTMLElement).dataset.stop);
          setActive(n === 0 ? null : n);
        }
      },
      { rootMargin: "-45% 0px -50% 0px" },
    );
    for (const el of sectionRefs.current) if (el) observer.observe(el);
    return () => observer.disconnect();
  }, [count]);

  const goTo = (n: number) => {
    const clamped = Math.max(0, Math.min(count, n));
    const el = sectionRefs.current[clamped];
    if (!el) return;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    el.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "center" });
    el.querySelector<HTMLElement>("[data-heading]")?.focus({ preventScroll: true });
    setActive(clamped === 0 ? null : clamped);
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      if (target?.closest("input, textarea, select, [contenteditable=true]") || e.altKey || e.ctrlKey || e.metaKey) return;
      if (e.key === "ArrowRight" || e.key === "j") {
        e.preventDefault();
        goTo((active ?? 0) + 1);
      } else if (e.key === "ArrowLeft" || e.key === "k") {
        e.preventDefault();
        goTo((active ?? 0) - 1);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  return (
    <article className="grid lg:grid-cols-[minmax(0,1fr)_minmax(0,1.15fr)]">
      <div className="relative order-1 h-[45vh] min-h-[300px] lg:sticky lg:top-[60px] lg:order-2 lg:h-[calc(100dvh-60px)]">
        <AtlasMap
          label={`Route map of ${journey.title}`}
          className="size-full"
          routes={routes}
          stops={markers}
          activeStop={active}
          focus={focus}
          onSelectStop={goTo}
        />
        <div className="absolute bottom-4 left-4 flex gap-2">
          <button
            type="button"
            onClick={() => goTo((active ?? 0) - 1)}
            disabled={(active ?? 0) === 0}
            className="btn btn-secondary shadow-[var(--shadow-lift)]"
            aria-label="Previous stop"
          >
            <ArrowUp aria-hidden className="size-4" />
          </button>
          <button
            type="button"
            onClick={() => goTo((active ?? 0) + 1)}
            disabled={(active ?? 0) >= count}
            className="btn btn-primary shadow-[var(--shadow-lift)]"
          >
            <ArrowDown aria-hidden className="size-4" />
            {active == null ? "Start the journey" : active >= count ? "End of journey" : "Next stop"}
          </button>
        </div>
        <p className="sr-only" aria-live="polite">
          {active == null ? "Journey overview" : `Stop ${active} of ${count}: ${journey.stops[active - 1]?.title}`}
        </p>
      </div>

      <div className="order-2 lg:order-1">
        <section
          ref={(el) => {
            sectionRefs.current[0] = el;
          }}
          data-stop={0}
          className="border-b border-sandstone bg-sand px-6 py-10 sm:px-10"
        >
          <nav aria-label="Breadcrumb" className="mb-3 text-sm text-muted">
            <Link href="/journeys" className="hover:underline">
              Journeys
            </Link>{" "}
            / <span aria-current="page">{journey.title}</span>
          </nav>
          <span aria-hidden className="mb-3 block h-1.5 w-16 rounded-full" style={{ background: journey.color }} />
          <h1 data-heading tabIndex={-1} className="text-4xl font-semibold sm:text-5xl">
            {journey.title}
          </h1>
          <p className="mt-2 text-ink-soft">
            Field journey by <strong>{journey.fellow}</strong>, {journey.year}
            {journey.region ? ` · ${journey.region}` : ""}
          </p>
          <p className="mt-4 text-lg leading-relaxed text-ink-soft">{journey.summary}</p>
          <dl className="mt-5 flex flex-wrap gap-6 text-sm">
            <div className="flex items-center gap-2">
              <Footprints aria-hidden className="size-4 text-terracotta" />
              <dt className="sr-only">Stops</dt>
              <dd>{count} stops</dd>
            </div>
            <div className="flex items-center gap-2">
              <Route aria-hidden className="size-4 text-terracotta" />
              <dt className="sr-only">Distance</dt>
              <dd>{formatKm(journey.distance_km)} travelled</dd>
            </div>
          </dl>
          <p className="mt-6 text-sm text-muted">
            Scroll, or use <kbd className="rounded border border-sandstone bg-white px-1">←</kbd>{" "}
            <kbd className="rounded border border-sandstone bg-white px-1">→</kbd>, to follow the route.
          </p>
        </section>

        <ol>
          {journey.stops.map((stop, i) => {
            const n = i + 1;
            const isActive = active === n;
            return (
              <li key={stop.seq}>
                <section
                  ref={(el) => {
                    sectionRefs.current[n] = el;
                  }}
                  data-stop={n}
                  aria-labelledby={`stop-${n}`}
                  className={`border-b border-sandstone px-6 py-10 transition-colors sm:px-10 ${isActive ? "bg-white" : ""}`}
                >
                  <div className="flex items-start gap-4">
                    <span
                      aria-hidden
                      className={`flex size-10 shrink-0 items-center justify-center rounded-full text-lg font-bold text-white ${isActive ? "bg-terracotta" : "bg-indigo-ink"}`}
                    >
                      {n}
                    </span>
                    <div className="min-w-0 flex-1">
                      <h2 id={`stop-${n}`} data-heading tabIndex={-1} className="text-3xl font-semibold">
                        <span className="sr-only">Stop {n}: </span>
                        {stop.title}
                      </h2>
                      <p className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-sm text-muted">
                        {stop.visited_on && (
                          <span className="flex items-center gap-1">
                            <CalendarDays aria-hidden className="size-4" />
                            {formatDate(stop.visited_on)}
                          </span>
                        )}
                        {i > 0 && <span>+{formatKm(stop.leg_km)} from the previous stop</span>}
                      </p>
                    </div>
                  </div>

                  <blockquote className="mt-5 border-l-4 border-terracotta/40 pl-4 font-serif text-xl leading-relaxed text-ink-soft italic">
                    {stop.narrative}
                  </blockquote>

                  {stop.site && (
                    <Link
                      href={`/sites/${stop.site.slug}`}
                      className="card mt-5 flex items-center gap-3 p-3 transition-shadow hover:shadow-[var(--shadow-lift)]"
                    >
                      <Thumb src={stop.site.cover_url} alt="" className="size-14 shrink-0 rounded-lg" />
                      <span className="min-w-0 flex-1">
                        <span className="flex items-center gap-1 text-xs font-semibold text-muted uppercase">
                          <MapPin aria-hidden className="size-3" /> Site record
                        </span>
                        <span className="block font-semibold">{stop.site.name}</span>
                        {stop.site.name_native && (
                          <span lang={scriptLang(stop.site.name_native)} className="block text-sm text-ink-soft">
                            {stop.site.name_native}
                          </span>
                        )}
                      </span>
                    </Link>
                  )}

                  {stop.assets.length > 0 && (
                    <ul className="mt-5 grid grid-cols-3 gap-2" aria-label={`Material collected at ${stop.title}`}>
                      {stop.assets.slice(0, 6).map((a) => (
                        <li key={a.id}>
                          <Link href={`/assets/${a.id}`} className="group block" title={a.title}>
                            <Thumb
                              src={a.thumb_url}
                              alt={a.title}
                              kind={a.kind}
                              className="aspect-square w-full rounded-lg transition-opacity group-hover:opacity-85"
                            />
                            <span className="mt-1 block truncate text-xs text-muted">{kindLabel(a.kind)}</span>
                          </Link>
                        </li>
                      ))}
                    </ul>
                  )}
                </section>
              </li>
            );
          })}
        </ol>
        <div className="px-6 py-10 text-center sm:px-10">
          <p className="font-serif text-2xl font-semibold">End of the journey</p>
          <div className="mt-4 flex flex-wrap justify-center gap-3">
            <button type="button" className="btn btn-secondary" onClick={() => goTo(0)}>
              Back to the start
            </button>
            <Link href="/journeys" className="btn btn-primary">
              More journeys
            </Link>
          </div>
        </div>
      </div>
    </article>
  );
}
