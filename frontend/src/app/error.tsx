"use client";

import { ErrorState } from "@/components/ui/primitives";

/** `retry()` re-fetches the segment's server data before re-rendering (Next 16), unlike `reset()`. */
export default function RouteError({ error, retry }: { error: Error & { digest?: string }; retry: () => void }) {
  // Production builds replace server-render error messages with a generic notice; say something useful instead.
  const shown = error.digest
    ? new Error(
        "This page couldn't be loaded from the archive server. If the free server was asleep it needs up to a minute to start — please try again.",
      )
    : error;
  return (
    <div className="mx-auto w-full max-w-2xl px-4 py-16">
      <ErrorState error={shown} onRetry={retry} />
      {error.digest && <p className="mt-3 text-xs text-muted">Reference: {error.digest}</p>}
    </div>
  );
}
