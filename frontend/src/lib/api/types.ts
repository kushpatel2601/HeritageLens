/**
 * Friendly aliases over the generated OpenAPI schema (`npm run gen:api`). Components import from
 * here, never from `schema.d.ts`, so a backend rename surfaces as one type error in one place.
 */
import type { components, paths } from "./schema";

/**
 * Response bodies as openapi-fetch hands them back. Its `Readable<T>` widens tuples such as
 * `[number, number]` to `number[]`, so the aliases mirror that to stay assignable from client data.
 */
type Received<T> = T extends (infer E)[] ? Received<E>[] : T extends object ? { [K in keyof T]: Received<T[K]> } : T;
type S = { [K in keyof components["schemas"]]: Received<components["schemas"][K]> };

export type { paths };
export type AssetBrief = S["AssetBrief"];
export type AssetDetail = S["AssetDetail"];
export type AssetPage = S["Page_AssetBrief_"];
export type Chunk = S["ChunkOut"];
export type Entity = S["EntityOut"];
export type Health = S["Health"];
export type Job = S["JobOut"];
export type JobPage = S["Page_JobOut_"];
export type JourneyDetail = S["JourneyDetail"];
export type JourneyOut = S["JourneyOut"];
export type PageOut = S["PageOut"];
export type PhotoHit = S["PhotoHit"];
export type SearchHit = S["SearchHit"];
export type SearchResponse = S["SearchResponse"];
export type SiteDetail = S["SiteDetail"];
export type SiteHit = S["SiteHit"];
export type SiteOut = S["SiteOut"];
export type Snippet = S["Snippet"];
export type Stats = S["Stats"];
export type Stop = S["StopOut"];
export type Twin = S["TwinOut"];
export type TwinRequest = components["schemas"]["TwinRequest"];
export type UploadResult = S["UploadResult"];
export type Worker = S["WorkerOut"];

export type AssetKind = NonNullable<SearchParams["kind"]>[number];
export type AssetStatus = "queued" | "processing" | "ready" | "failed";
export type JobStatus = "queued" | "leased" | "succeeded" | "failed" | "dead";
export type TwinMethod = TwinRequest["method"];

export type SearchParams = NonNullable<paths["/api/v1/search"]["get"]["parameters"]["query"]>;
export type AssetListParams = NonNullable<paths["/api/v1/assets"]["get"]["parameters"]["query"]>;
export type JobListParams = NonNullable<paths["/api/v1/jobs"]["get"]["parameters"]["query"]>;

/** GeoJSON layers served by /sites/geojson, /journeys/geojson and /assets/geojson. */
export interface SiteFeatureProps {
  id: number;
  slug: string;
  name: string;
  name_native: string | null;
  category: string;
  era_start: number | null;
  era_label: string | null;
  unesco: boolean;
  assets: number;
  twins: number;
  cover_url: string | null;
}

export interface RouteFeatureProps {
  slug: string;
  title: string;
  color: string;
  year: number;
}

export interface AssetFeatureProps {
  id: number;
  kind: string;
  title: string;
  site_id: number | null;
  geo_source: string | null;
  thumb_url: string | null;
}

export interface Feature<G, P> {
  type: "Feature";
  id?: number | string;
  geometry: G;
  properties: P;
}

export interface FeatureCollection<G, P> {
  type: "FeatureCollection";
  features: Feature<G, P>[];
}

export type PointGeometry = { type: "Point"; coordinates: [number, number] };
export type LineGeometry = { type: "LineString"; coordinates: [number, number][] };

export type SitesGeoJSON = FeatureCollection<PointGeometry, SiteFeatureProps>;
export type RoutesGeoJSON = FeatureCollection<LineGeometry, RouteFeatureProps>;
export type AssetsGeoJSON = FeatureCollection<PointGeometry, AssetFeatureProps>;

/** Payloads of the `job` / `asset` Server-Sent Events (backend/app/services/events.py). */
export interface JobEvent {
  id: number;
  type: string;
  queue: string;
  status: JobStatus;
  attempts: number;
  asset_id: number | null;
  asset_title: string | null;
  site_id: number | null;
  site_name: string | null;
  site_slug: string | null;
  error: string | null;
  result: Record<string, unknown> | null;
  updated_at: string;
}

export interface AssetEvent {
  id: number;
  kind: string;
  title: string;
  status: AssetStatus;
  error: string | null;
  language: string | null;
  site_id: number | null;
  lat: number | null;
  lon: number | null;
  thumb_url: string | null;
  updated_at: string;
}

export type LiveEvent = { kind: "job"; data: JobEvent } | { kind: "asset"; data: AssetEvent };
