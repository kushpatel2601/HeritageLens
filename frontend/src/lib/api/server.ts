/**
 * Server-side loaders for detail pages. `cache()` dedupes the request between generateMetadata
 * and the page body within one render; data is intentionally *not* `use cache`d because the
 * archive changes as the pipeline runs and live clients re-validate through TanStack Query.
 */
import { notFound } from "next/navigation";
import { cache } from "react";

import { api, ApiError, unwrap } from "./client";

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

/** Retry while the free API host wakes up, keeping the total wait short enough for a server render. */
async function withWakeRetry<T>(request: () => Promise<T>, delays = [1500, 3000, 6000]): Promise<T> {
  for (const delay of delays) {
    try {
      return await request();
    } catch (error) {
      if (!(error instanceof ApiError && error.isUnavailable)) throw error;
      await sleep(delay);
    }
  }
  return request();
}

async function orNotFound<T>(promise: Promise<T>): Promise<T> {
  try {
    return await promise;
  } catch (error) {
    if (error instanceof ApiError && (error.isNotFound || error.status === 422)) notFound();
    throw error;
  }
}

export const loadSite = cache((slug: string) =>
  orNotFound(withWakeRetry(() => unwrap(api.GET("/api/v1/sites/{slug}", { params: { path: { slug } } })))),
);

export const loadJourney = cache((slug: string) =>
  orNotFound(withWakeRetry(() => unwrap(api.GET("/api/v1/journeys/{slug}", { params: { path: { slug } } })))),
);

export const loadAsset = cache((id: number) => {
  if (!Number.isSafeInteger(id) || id <= 0) notFound();
  return orNotFound(
    withWakeRetry(() => unwrap(api.GET("/api/v1/assets/{asset_id}", { params: { path: { asset_id: id } } }))),
  );
});

export const loadChunks = cache((id: number) =>
  orNotFound(
    withWakeRetry(() => unwrap(api.GET("/api/v1/assets/{asset_id}/chunks", { params: { path: { asset_id: id } } }))),
  ),
);
