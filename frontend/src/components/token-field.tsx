"use client";

import { KeyRound } from "lucide-react";
import { useId, useSyncExternalStore } from "react";

/**
 * Optional curator token for write endpoints (backend `HL_INGEST_TOKEN`). Kept in sessionStorage
 * so it survives navigation but not the browser session, and shared by every form via an
 * external store so entering it once unlocks uploads, twin builds and retries together.
 */
const KEY = "hl:ingest-token";
const listeners = new Set<() => void>();

function read(): string {
  try {
    return sessionStorage.getItem(KEY) ?? "";
  } catch {
    return "";
  }
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function setIngestToken(token: string): void {
  try {
    if (token) sessionStorage.setItem(KEY, token);
    else sessionStorage.removeItem(KEY);
  } catch {
    // Storage disabled (private mode): the token simply isn't remembered.
  }
  listeners.forEach((l) => l());
}

export function useIngestToken(): string {
  return useSyncExternalStore(subscribe, read, () => "");
}

/** Collapsed by default; opened automatically after a 401 so the user knows what is missing. */
export function TokenField({ forceOpen = false }: { forceOpen?: boolean }) {
  const token = useIngestToken();
  const id = useId();
  return (
    <details open={forceOpen || undefined} className="rounded-lg border border-sandstone bg-sand/40 text-sm">
      <summary className="flex cursor-pointer items-center gap-2 px-3 py-2 font-semibold text-ink-soft">
        <KeyRound aria-hidden className="size-4" />
        Curator token {token ? "(set)" : "(only if this server requires one)"}
      </summary>
      <div className="space-y-1 px-3 pb-3">
        <label htmlFor={id} className="sr-only">
          Curator token
        </label>
        <input
          id={id}
          type="password"
          autoComplete="off"
          value={token}
          onChange={(e) => setIngestToken(e.target.value.trim())}
          placeholder="Paste the HL_INGEST_TOKEN value"
          className="field"
        />
        <p className="text-xs text-muted">Stored for this browser tab only.</p>
      </div>
    </details>
  );
}
