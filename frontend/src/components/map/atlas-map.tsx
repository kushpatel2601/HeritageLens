"use client";

import {
  AttributionControl,
  LngLatBounds,
  Map as MapLibre,
  Marker,
  NavigationControl,
  setWorkerUrl,
  type GeoJSONSource,
  type ExpressionSpecification,
  type MapGeoJSONFeature,
  type StyleSpecification,
} from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { useEffect, useEffectEvent, useRef, useState } from "react";

import type {
  AssetFeatureProps,
  AssetsGeoJSON,
  RoutesGeoJSON,
  SiteFeatureProps,
  SitesGeoJSON,
} from "@/lib/api/types";
import { CATEGORY_COLORS } from "@/lib/format";

setWorkerUrl("/vendor/maplibre-gl-worker.mjs");

const STYLE_URL = process.env.NEXT_PUBLIC_MAP_STYLE ?? "https://tiles.openfreemap.org/styles/positron";

/** Raster OSM basemap: used when the vector style cannot be fetched (offline demo, blocked CDN). */
const FALLBACK_STYLE: StyleSpecification = {
  version: 8,
  sources: {
    osm: {
      type: "raster",
      tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
      tileSize: 256,
      maxzoom: 19,
      attribution: "© OpenStreetMap contributors",
    },
  },
  layers: [
    { id: "paper", type: "background", paint: { "background-color": "#f4ecdf" } },
    { id: "osm", type: "raster", source: "osm", paint: { "raster-saturation": -0.6, "raster-opacity": 0.85 } },
  ],
};

let stylePromise: Promise<string | StyleSpecification> | null = null;

/** Probe the vector style once per tab (2.5 s budget) and fall back to raster tiles. */
function resolveStyle(): Promise<string | StyleSpecification> {
  stylePromise ??= fetch(STYLE_URL, { signal: AbortSignal.timeout(2500) })
    .then((r) => (r.ok ? STYLE_URL : FALLBACK_STYLE))
    .catch(() => FALLBACK_STYLE);
  return stylePromise;
}

const EMPTY = { type: "FeatureCollection", features: [] } as const;
// Covers every seeded site, from Kutch to Delhi and south to Hampi.
const INDIA_WEST: [number, number, number, number] = [68.0, 14.5, 78.5, 29.5];

const categoryMatch = [
  "match",
  ["get", "category"],
  ...Object.entries(CATEGORY_COLORS).flat(),
  "#57534e",
] as unknown as ExpressionSpecification;

export interface StopMarker {
  seq: number;
  title: string;
  lat: number;
  lon: number;
}

export type MapFocus =
  | { kind: "point"; lon: number; lat: number; zoom?: number }
  | { kind: "bounds"; bbox: [number, number, number, number]; padding?: number };

export interface AtlasMapProps {
  sites?: SitesGeoJSON;
  routes?: RoutesGeoJSON;
  assets?: AssetsGeoJSON;
  showSites?: boolean;
  showRoutes?: boolean;
  showAssets?: boolean;
  selectedSiteId?: number | null;
  highlightRoute?: string | null;
  stops?: StopMarker[];
  activeStop?: number | null;
  focus?: MapFocus | null;
  onSelectSite?: (site: SiteFeatureProps) => void;
  onSelectAsset?: (asset: AssetFeatureProps) => void;
  onSelectStop?: (seq: number) => void;
  label: string;
  className?: string;
}

export default function AtlasMap({
  sites,
  routes,
  assets,
  showSites = true,
  showRoutes = true,
  showAssets = false,
  selectedSiteId = null,
  highlightRoute = null,
  stops,
  activeStop = null,
  focus = null,
  onSelectSite,
  onSelectAsset,
  onSelectStop,
  label,
  className,
}: AtlasMapProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [map, setMap] = useState<MapLibre | null>(null);
  const [failed, setFailed] = useState(false);

  const selectSite = useEffectEvent((p: SiteFeatureProps) => onSelectSite?.(p));
  const selectAsset = useEffectEvent((p: AssetFeatureProps) => onSelectAsset?.(p));
  const selectStop = useEffectEvent((seq: number) => onSelectStop?.(seq));

  // Create / destroy the map. Under Cache Components a hidden route's effects are cleaned up, so
  // the WebGL context is released while the page is in the back-forward <Activity> cache.
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    let disposed = false;
    let instance: MapLibre | null = null;

    void resolveStyle().then((style) => {
      if (disposed) return;
      try {
        instance = new MapLibre({
          container,
          style,
          bounds: INDIA_WEST,
          fitBoundsOptions: { padding: 24 },
          attributionControl: false,
          cooperativeGestures: false,
          maxPitch: 60,
        });
      } catch {
        setFailed(true); // WebGL unavailable
        return;
      }
      const m = instance;
      m.addControl(new NavigationControl({ visualizePitch: true }), "top-right");
      m.addControl(new AttributionControl({ compact: true }), "bottom-right");
      m.on("load", () => {
        addLayers(m);
        bindInteractions(m, {
          site: (p) => selectSite(p),
          asset: (p) => selectAsset(p),
        });
        collapseAttributionWhenNarrow(m);
        if (!disposed) setMap(m);
      });
    });

    return () => {
      disposed = true;
      instance?.remove();
      setMap(null);
    };
  }, []);

  useEffect(() => setSource(map, "sites", sites), [map, sites]);
  useEffect(() => setSource(map, "routes", routes), [map, routes]);
  useEffect(() => setSource(map, "assets", assets), [map, assets]);

  useEffect(() => {
    if (!map) return;
    setVisible(map, ["sites-halo", "sites-circle"], showSites);
    setVisible(map, ["routes-casing", "routes-line"], showRoutes);
    setVisible(map, ["assets-cluster", "assets-point"], showAssets);
  }, [map, showSites, showRoutes, showAssets]);

  useEffect(() => {
    if (!map) return;
    map.setFilter("sites-halo", ["==", ["get", "id"], selectedSiteId ?? -1]);
  }, [map, selectedSiteId]);

  useEffect(() => {
    if (!map) return;
    const match: ExpressionSpecification = ["==", ["get", "slug"], highlightRoute ?? ""];
    map.setPaintProperty("routes-line", "line-opacity", highlightRoute ? ["case", match, 1, 0.2] : 0.9);
    map.setPaintProperty("routes-line", "line-width", highlightRoute ? ["case", match, 5, 2.5] : 3.5);
  }, [map, highlightRoute]);

  // Numbered stop markers are DOM buttons so they are focusable and announced by screen readers.
  useEffect(() => {
    if (!map || !stops?.length) return;
    const markers = stops.map((stop) => {
      const el = document.createElement("button");
      el.type = "button";
      el.className =
        "flex size-8 items-center justify-center rounded-full border-2 border-white bg-indigo-ink text-sm font-bold text-white shadow-lg transition-transform data-[active=true]:scale-125 data-[active=true]:bg-terracotta";
      el.textContent = String(stop.seq);
      el.setAttribute("aria-label", `Stop ${stop.seq}: ${stop.title}`);
      el.dataset.seq = String(stop.seq);
      el.addEventListener("click", () => selectStop(stop.seq));
      return new Marker({ element: el }).setLngLat([stop.lon, stop.lat]).addTo(map);
    });
    return () => markers.forEach((m) => m.remove());
  }, [map, stops]);

  useEffect(() => {
    if (!map) return;
    for (const el of map.getContainer().querySelectorAll<HTMLElement>("[data-seq]")) {
      el.dataset.active = String(Number(el.dataset.seq) === activeStop);
    }
  }, [map, activeStop, stops]);

  useEffect(() => {
    if (!map || !focus) return;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (focus.kind === "point") {
      map.flyTo({ center: [focus.lon, focus.lat], zoom: focus.zoom ?? 11, essential: false, animate: !reduce, duration: 1800 });
    } else {
      const [w, s, e, n] = focus.bbox;
      map.fitBounds(new LngLatBounds([w, s], [e, n]), { padding: focus.padding ?? 64, animate: !reduce, maxZoom: 12 });
    }
  }, [map, focus]);

  return (
    <div className={className} style={{ position: "relative" }}>
      {/* Inline style: maplibre-gl.css sets `.maplibregl-map { position: relative }` unlayered, which beats Tailwind's layered utilities. */}
      <div ref={containerRef} role="region" aria-label={label} style={{ position: "absolute", inset: 0 }} />
      {failed && (
        <div className="absolute inset-0 flex items-center justify-center bg-sand p-6 text-center text-sm text-muted">
          The interactive map needs WebGL, which this browser has disabled. Every site is still listed alongside.
        </div>
      )}
    </div>
  );
}

/**
 * MapLibre opens compact attribution on load; on narrow maps it then covers overlay controls (the
 * journey buttons). Start it collapsed there; the (i) button and the site footer keep the credits.
 */
function collapseAttributionWhenNarrow(m: MapLibre): void {
  if (m.getContainer().clientWidth >= 768) return;
  const attribution = m.getContainer().querySelector(".maplibregl-ctrl-attrib");
  attribution?.classList.remove("maplibregl-compact-show");
  attribution?.removeAttribute("open");
}

function addLayers(m: MapLibre): void {
  m.addSource("routes", { type: "geojson", data: EMPTY as never });
  m.addSource("assets", {
    type: "geojson",
    data: EMPTY as never,
    cluster: true,
    clusterRadius: 40,
    clusterMaxZoom: 13,
  });
  m.addSource("sites", { type: "geojson", data: EMPTY as never });

  m.addLayer({
    id: "routes-casing",
    type: "line",
    source: "routes",
    layout: { "line-cap": "round", "line-join": "round" },
    paint: { "line-color": "#ffffff", "line-width": 7, "line-opacity": 0.85 },
  });
  m.addLayer({
    id: "routes-line",
    type: "line",
    source: "routes",
    layout: { "line-cap": "round", "line-join": "round" },
    paint: { "line-color": ["get", "color"], "line-width": 3.5, "line-opacity": 0.9, "line-dasharray": [2, 1.2] },
  });
  m.addLayer({
    id: "assets-cluster",
    type: "circle",
    source: "assets",
    filter: ["has", "point_count"],
    paint: {
      "circle-color": "#1e3a5f",
      "circle-opacity": 0.75,
      "circle-radius": ["step", ["get", "point_count"], 10, 10, 14, 50, 20],
      "circle-stroke-color": "#ffffff",
      "circle-stroke-width": 2,
    },
  });
  m.addLayer({
    id: "assets-point",
    type: "circle",
    source: "assets",
    filter: ["!", ["has", "point_count"]],
    paint: {
      "circle-color": ["match", ["get", "kind"], "photo", "#b45309", "#1e3a5f"],
      "circle-radius": 4.5,
      "circle-stroke-color": "#ffffff",
      "circle-stroke-width": 1.5,
    },
  });
  m.addLayer({
    id: "sites-halo",
    type: "circle",
    source: "sites",
    filter: ["==", ["get", "id"], -1],
    paint: { "circle-color": "#b45309", "circle-opacity": 0.25, "circle-radius": 20, "circle-blur": 0.2 },
  });
  m.addLayer({
    id: "sites-circle",
    type: "circle",
    source: "sites",
    paint: {
      "circle-color": categoryMatch,
      "circle-radius": ["interpolate", ["linear"], ["zoom"], 4, 6, 10, 10],
      "circle-stroke-color": ["case", ["get", "unesco"], "#fbbf24", "#ffffff"],
      "circle-stroke-width": ["case", ["get", "unesco"], 3, 2],
    },
  });
}

function bindInteractions(
  m: MapLibre,
  on: { site: (p: SiteFeatureProps) => void; asset: (p: AssetFeatureProps) => void },
): void {
  for (const layer of ["sites-circle", "assets-point", "assets-cluster"]) {
    m.on("mouseenter", layer, () => (m.getCanvas().style.cursor = "pointer"));
    m.on("mouseleave", layer, () => (m.getCanvas().style.cursor = ""));
  }
  m.on("click", "sites-circle", (e) => {
    const f = e.features?.[0] as MapGeoJSONFeature | undefined;
    if (f) on.site(f.properties as SiteFeatureProps);
  });
  m.on("click", "assets-point", (e) => {
    const f = e.features?.[0] as MapGeoJSONFeature | undefined;
    if (f) on.asset(f.properties as AssetFeatureProps);
  });
  m.on("click", "assets-cluster", async (e) => {
    const f = e.features?.[0];
    if (!f || f.geometry.type !== "Point") return;
    const zoom = await (m.getSource("assets") as GeoJSONSource).getClusterExpansionZoom(f.properties.cluster_id);
    m.easeTo({ center: f.geometry.coordinates as [number, number], zoom });
  });
}

function setSource(m: MapLibre | null, id: string, data: object | undefined): void {
  if (!m || !data) return;
  (m.getSource(id) as GeoJSONSource | undefined)?.setData(data as never);
}

function setVisible(m: MapLibre, layers: string[], visible: boolean): void {
  for (const layer of layers) m.setLayoutProperty(layer, "visibility", visible ? "visible" : "none");
}
