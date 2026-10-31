/**
 * One EventSource per tab, fanned out to the UI. Pipeline events are coalesced into query-cache
 * invalidations (at most one refetch per key per flush window) so a GPU worker finishing hundreds
 * of jobs a minute cannot trigger a refetch storm. A dropped stream is reopened with backoff, and
 * whatever is on screen is refetched once it is back.
 */
import type { QueryClient, QueryKey } from "@tanstack/react-query";

import { keys } from "./api/queries";
import type { AssetEvent, JobEvent, LiveEvent } from "./api/types";

export type LiveStatus = "idle" | "connecting" | "open" | "reconnecting" | "unsupported";

export interface LiveSnapshot {
  status: LiveStatus;
  events: ReadonlyArray<LiveEvent & { receivedAt: number }>;
}

const FEED_SIZE = 60;
const RETRY_MIN_MS = 2_000;
const RETRY_MAX_MS = 30_000;

/** Query keys that become stale when an event arrives. Exported for unit tests. */
export function keysToInvalidate(event: LiveEvent): QueryKey[] {
  const out: QueryKey[] = [keys.stats()];
  if (event.kind === "job") {
    const job: JobEvent = event.data;
    out.push(keys.jobs());
    if (job.asset_id != null) out.push(keys.asset(job.asset_id));
    if (job.status === "succeeded" || job.status === "dead") out.push(keys.workers());
    if (job.type === "reconstruct3d" && job.status === "succeeded") out.push(keys.sites(), keys.twins());
  } else {
    const asset: AssetEvent = event.data;
    out.push(keys.asset(asset.id), keys.assets());
    if (asset.site_id != null) out.push(keys.sites());
    if (asset.status === "ready") out.push(keys.chunks(asset.id), keys.sitesGeo(), keys.assetsGeo());
  }
  return out;
}

type Listener = () => void;
type EventListener = (event: LiveEvent) => void;

export class LiveStore {
  private snapshot: LiveSnapshot = { status: "idle", events: [] };
  private readonly listeners = new Set<Listener>();
  private readonly eventListeners = new Set<EventListener>();
  private readonly pending = new Map<string, QueryKey>();
  private source: EventSource | null = null;
  private flushTimer: ReturnType<typeof setTimeout> | null = null;
  private retryTimer: ReturnType<typeof setTimeout> | null = null;
  private retryMs = RETRY_MIN_MS;
  private dropped = false;
  private refs = 0;

  constructor(
    private readonly queryClient: QueryClient,
    private readonly url = "/api/v1/events",
    private readonly flushMs = 800,
  ) {}

  subscribe = (listener: Listener): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  getSnapshot = (): LiveSnapshot => this.snapshot;

  getServerSnapshot = (): LiveSnapshot => SERVER_SNAPSHOT;

  onEvent(listener: EventListener): () => void {
    this.eventListeners.add(listener);
    return () => this.eventListeners.delete(listener);
  }

  /** Reference-counted so React StrictMode's double effects never open two connections. */
  connect(): () => void {
    this.refs += 1;
    if (!this.source && !this.retryTimer) this.open();
    return () => {
      this.refs -= 1;
      if (this.refs === 0) this.close();
    };
  }

  private open(): void {
    if (typeof EventSource === "undefined") {
      this.setStatus("unsupported");
      return;
    }
    this.setStatus(this.dropped ? "reconnecting" : "connecting");
    const source = new EventSource(this.url);
    source.onopen = () => {
      this.retryMs = RETRY_MIN_MS;
      if (this.dropped) {
        // Anything that happened while disconnected was never streamed, so refetch what is on screen.
        this.dropped = false;
        void this.queryClient.invalidateQueries();
      }
      this.setStatus("open");
    };
    source.onerror = () => {
      this.dropped = true;
      this.setStatus("reconnecting");
      if (source.readyState !== EventSource.CLOSED) return;
      // The browser stops retrying after a non-2xx reply, e.g. while the API redeploys or wakes up.
      source.close();
      this.source = null;
      this.retryTimer = setTimeout(() => {
        this.retryTimer = null;
        if (this.refs > 0) this.open();
      }, this.retryMs);
      this.retryMs = Math.min(this.retryMs * 2, RETRY_MAX_MS);
    };
    source.addEventListener("job", (e) => this.receive("job", e));
    source.addEventListener("asset", (e) => this.receive("asset", e));
    this.source = source;
  }

  private close(): void {
    this.source?.close();
    this.source = null;
    if (this.flushTimer) clearTimeout(this.flushTimer);
    this.flushTimer = null;
    if (this.retryTimer) clearTimeout(this.retryTimer);
    this.retryTimer = null;
    this.retryMs = RETRY_MIN_MS;
    this.dropped = false;
    this.setStatus("idle");
  }

  /** Visible for tests: feed one raw SSE message through the store. */
  receive(kind: "job" | "asset", message: MessageEvent<string> | { data: string }): void {
    let data: unknown;
    try {
      data = JSON.parse(message.data);
    } catch {
      return;
    }
    if (!data || typeof data !== "object" || typeof (data as { id?: unknown }).id !== "number") return;
    const event = { kind, data } as LiveEvent;
    this.snapshot = {
      ...this.snapshot,
      events: [{ ...event, receivedAt: Date.now() }, ...this.snapshot.events].slice(0, FEED_SIZE),
    };
    this.emit();
    for (const listener of this.eventListeners) listener(event);
    for (const key of keysToInvalidate(event)) this.pending.set(JSON.stringify(key), key);
    this.flushTimer ??= setTimeout(() => this.flush(), this.flushMs);
  }

  flush(): void {
    this.flushTimer = null;
    const batch = [...this.pending.values()];
    this.pending.clear();
    for (const queryKey of batch) void this.queryClient.invalidateQueries({ queryKey });
  }

  private setStatus(status: LiveStatus): void {
    if (this.snapshot.status === status) return;
    this.snapshot = { ...this.snapshot, status };
    this.emit();
  }

  private emit(): void {
    for (const listener of this.listeners) listener();
  }
}

const SERVER_SNAPSHOT: LiveSnapshot = { status: "idle", events: [] };
