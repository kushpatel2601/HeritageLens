"use client";

import { ErrorState } from "@/components/ui/primitives";

/** `retry()` re-fetches the segment's server data before re-rendering (Next 16), unlike `reset()`. */
export default function RouteError({ error, retry }: { error: Error & { digest?: string }; retry: () => void }) {
  return (
    <div className="mx-auto w-full max-w-2xl px-4 py-16">
      <ErrorState error={error} onRetry={retry} />
      {error.digest && <p className="mt-3 text-xs text-muted">Reference: {error.digest}</p>}
    </div>
  );
}
