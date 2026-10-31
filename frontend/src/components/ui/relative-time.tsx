"use client";

import { useSyncExternalStore } from "react";

import { formatDate, formatRelative } from "@/lib/format";

const TICK_MS = 15_000;

function subscribe(onTick: () => void): () => void {
  const timer = window.setInterval(onTick, TICK_MS);
  return () => window.clearInterval(timer);
}

// Rounded up to the tick so repeated reads agree and something that just finished never reads "in a moment".
const browserNow = () => Math.ceil(Date.now() / TICK_MS) * TICK_MS;
const serverNow = () => null;

/**
 * "3 hours ago", worked out in the browser only. Pages are prerendered and cached at the edge, so a
 * relative time baked into the HTML would be stale and would not match what hydration renders. The
 * server, and the browser while hydrating, print the calendar date instead; it is swapped right after.
 */
export function RelativeTime({ iso }: { iso: string | null | undefined }) {
  const now = useSyncExternalStore(subscribe, browserNow, serverNow);
  if (!iso) return "—";
  return (
    <time dateTime={iso} title={formatDate(iso)}>
      {now === null ? formatDate(iso) : formatRelative(iso, now)}
    </time>
  );
}
