/**
 * Server-side loaders for detail pages. `cache()` dedupes the request between generateMetadata
 * and the page body within one render; data is intentionally *not* `use cache`d because the
 * archive changes as the pipeline runs and live clients re-validate through TanStack Query.
 */
import { notFound } from "next/navigation";
import { cache } from "react";

import { api, ApiError, unwrap } from "./client";

async function orNotFound<T>(promise: Promise<T>): Promise<T> {
  try {
    return await promise;
  } catch (error) {
    if (error instanceof ApiError && (error.isNotFound || error.status === 422)) notFound();
    throw error;
  }
}

export const loadSite = cache((slug: string) =>
  orNotFound(unwrap(api.GET("/api/v1/sites/{slug}", { params: { path: { slug } } }))),
);

export const loadJourney = cache((slug: string) =>
  orNotFound(unwrap(api.GET("/api/v1/journeys/{slug}", { params: { path: { slug } } }))),
);

export const loadAsset = cache((id: number) => {
  if (!Number.isSafeInteger(id) || id <= 0) notFound();
  return orNotFound(unwrap(api.GET("/api/v1/assets/{asset_id}", { params: { path: { asset_id: id } } })));
});

export const loadChunks = cache((id: number) =>
  orNotFound(unwrap(api.GET("/api/v1/assets/{asset_id}/chunks", { params: { path: { asset_id: id } } }))),
);
