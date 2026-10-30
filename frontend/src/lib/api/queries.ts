/**
 * TanStack Query option factories: one place that owns every query key and fetcher, shared by
 * client components (useQuery) and the live-event invalidation logic.
 */
import { queryOptions } from "@tanstack/react-query";

import { api, getJSON, unwrap } from "./client";
import type {
  AssetListParams,
  AssetsGeoJSON,
  JobListParams,
  RoutesGeoJSON,
  SearchParams,
  SitesGeoJSON,
} from "./types";

export const keys = {
  all: ["hl"] as const,
  stats: () => [...keys.all, "stats"] as const,
  health: () => [...keys.all, "health"] as const,
  sites: () => [...keys.all, "sites"] as const,
  sitesGeo: () => [...keys.all, "sites", "geojson"] as const,
  site: (slug: string) => [...keys.all, "sites", slug] as const,
  journeys: () => [...keys.all, "journeys"] as const,
  routesGeo: () => [...keys.all, "journeys", "geojson"] as const,
  journey: (slug: string) => [...keys.all, "journeys", slug] as const,
  search: (p: SearchParams) => [...keys.all, "search", p] as const,
  assets: () => [...keys.all, "assets"] as const,
  assetList: (p: AssetListParams) => [...keys.all, "assets", "list", p] as const,
  assetsGeo: () => [...keys.all, "assets", "geojson"] as const,
  asset: (id: number) => [...keys.all, "assets", id] as const,
  chunks: (id: number) => [...keys.all, "assets", id, "chunks"] as const,
  jobs: () => [...keys.all, "jobs"] as const,
  jobList: (p: JobListParams) => [...keys.all, "jobs", p] as const,
  workers: () => [...keys.all, "workers"] as const,
  twins: () => [...keys.all, "twins"] as const,
};

export const statsQuery = () =>
  queryOptions({ queryKey: keys.stats(), queryFn: () => unwrap(api.GET("/api/v1/stats")), staleTime: 10_000 });

export const healthQuery = () =>
  queryOptions({
    queryKey: keys.health(),
    queryFn: () => unwrap(api.GET("/api/v1/ready")),
    refetchInterval: 30_000,
    retry: false,
  });

export const sitesQuery = () =>
  queryOptions({ queryKey: keys.sites(), queryFn: () => unwrap(api.GET("/api/v1/sites")), staleTime: 60_000 });

export const sitesGeoQuery = () =>
  queryOptions({
    queryKey: keys.sitesGeo(),
    queryFn: () => getJSON<SitesGeoJSON>("/api/v1/sites/geojson"),
    staleTime: 60_000,
  });

export const siteQuery = (slug: string) =>
  queryOptions({
    queryKey: keys.site(slug),
    queryFn: () => unwrap(api.GET("/api/v1/sites/{slug}", { params: { path: { slug } } })),
  });

export const journeysQuery = () =>
  queryOptions({ queryKey: keys.journeys(), queryFn: () => unwrap(api.GET("/api/v1/journeys")), staleTime: 60_000 });

export const journeyQuery = (slug: string) =>
  queryOptions({
    queryKey: keys.journey(slug),
    queryFn: () => unwrap(api.GET("/api/v1/journeys/{slug}", { params: { path: { slug } } })),
    staleTime: 60_000,
  });

export const routesGeoQuery = () =>
  queryOptions({
    queryKey: keys.routesGeo(),
    queryFn: () => getJSON<RoutesGeoJSON>("/api/v1/journeys/geojson"),
    staleTime: 60_000,
  });

export const searchQuery = (params: SearchParams) =>
  queryOptions({
    queryKey: keys.search(params),
    queryFn: ({ signal }) => unwrap(api.GET("/api/v1/search", { params: { query: params }, signal })),
    enabled: params.q.trim().length > 0,
    staleTime: 30_000,
  });

export const assetListQuery = (params: AssetListParams) =>
  queryOptions({
    queryKey: keys.assetList(params),
    queryFn: ({ signal }) => unwrap(api.GET("/api/v1/assets", { params: { query: params }, signal })),
    placeholderData: (previous) => previous,
  });

export const assetsGeoQuery = () =>
  queryOptions({
    queryKey: keys.assetsGeo(),
    queryFn: () => getJSON<AssetsGeoJSON>("/api/v1/assets/geojson"),
    staleTime: 30_000,
  });

export const assetQuery = (id: number) =>
  queryOptions({
    queryKey: keys.asset(id),
    queryFn: () => unwrap(api.GET("/api/v1/assets/{asset_id}", { params: { path: { asset_id: id } } })),
  });

export const chunksQuery = (id: number) =>
  queryOptions({
    queryKey: keys.chunks(id),
    queryFn: () => unwrap(api.GET("/api/v1/assets/{asset_id}/chunks", { params: { path: { asset_id: id } } })),
  });

export const jobListQuery = (params: JobListParams) =>
  queryOptions({
    queryKey: keys.jobList(params),
    queryFn: ({ signal }) => unwrap(api.GET("/api/v1/jobs", { params: { query: params }, signal })),
    placeholderData: (previous) => previous,
  });

export const workersQuery = () =>
  queryOptions({
    queryKey: keys.workers(),
    queryFn: () => unwrap(api.GET("/api/v1/workers")),
    refetchInterval: 15_000,
  });
