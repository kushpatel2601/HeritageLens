import type { QueryClient } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { keys } from "@/lib/api/queries";
import type { AssetEvent, JobEvent } from "@/lib/api/types";
import { keysToInvalidate, LiveStore } from "@/lib/live";

function job(overrides: Partial<JobEvent> = {}): JobEvent {
  return {
    id: 7,
    type: "ocr",
    queue: "gpu",
    status: "leased",
    attempts: 1,
    asset_id: 41,
    asset_title: "Patan diary",
    site_id: null,
    site_name: null,
    site_slug: null,
    error: null,
    result: null,
    updated_at: "2026-10-30T12:00:00Z",
    ...overrides,
  };
}

function asset(overrides: Partial<AssetEvent> = {}): AssetEvent {
  return {
    id: 41,
    kind: "journal",
    title: "Patan diary",
    status: "processing",
    error: null,
    language: "hi",
    site_id: null,
    lat: null,
    lon: null,
    thumb_url: null,
    updated_at: "2026-10-30T12:00:00Z",
    ...overrides,
  };
}

describe("keysToInvalidate", () => {
  it("refreshes stats, jobs and the job's asset while a job runs", () => {
    expect(keysToInvalidate({ kind: "job", data: job() })).toEqual([keys.stats(), keys.jobs(), keys.asset(41)]);
  });

  it("refreshes workers when a job finishes, and twins when a reconstruction succeeds", () => {
    const keysFor = keysToInvalidate({
      kind: "job",
      data: job({ type: "reconstruct3d", status: "succeeded", asset_id: null, site_id: 3 }),
    });
    expect(keysFor).toEqual([keys.stats(), keys.jobs(), keys.workers(), keys.sites(), keys.twins()]);
  });

  it("refreshes text and map layers once an asset is ready", () => {
    const keysFor = keysToInvalidate({ kind: "asset", data: asset({ status: "ready", site_id: 2 }) });
    expect(keysFor).toEqual([
      keys.stats(),
      keys.asset(41),
      keys.assets(),
      keys.sites(),
      keys.chunks(41),
      keys.sitesGeo(),
      keys.assetsGeo(),
    ]);
  });
});

describe("LiveStore", () => {
  let invalidateQueries: ReturnType<typeof vi.fn>;
  let store: LiveStore;

  beforeEach(() => {
    vi.useFakeTimers();
    invalidateQueries = vi.fn().mockResolvedValue(undefined);
    store = new LiveStore({ invalidateQueries } as unknown as QueryClient, "/events", 800);
  });

  afterEach(() => vi.useRealTimers());

  it("coalesces a burst of events into one invalidation per key", () => {
    for (let i = 0; i < 25; i++) store.receive("job", { data: JSON.stringify(job({ id: i })) });
    store.receive("asset", { data: JSON.stringify(asset()) });
    expect(invalidateQueries).not.toHaveBeenCalled();

    vi.advanceTimersByTime(800);
    const invalidated = invalidateQueries.mock.calls.map(([arg]) => (arg as { queryKey: unknown }).queryKey);
    expect(invalidated).toEqual([keys.stats(), keys.jobs(), keys.asset(41), keys.assets()]);

    store.receive("job", { data: JSON.stringify(job()) });
    vi.advanceTimersByTime(800);
    expect(invalidateQueries).toHaveBeenCalledTimes(7);
  });

  it("keeps a newest-first feed and notifies subscribers and event listeners", () => {
    const changed = vi.fn();
    const onEvent = vi.fn();
    store.subscribe(changed);
    store.onEvent(onEvent);

    store.receive("job", { data: JSON.stringify(job({ id: 1 })) });
    store.receive("asset", { data: JSON.stringify(asset({ id: 2 })) });

    expect(store.getSnapshot().events.map((e) => `${e.kind}:${e.data.id}`)).toEqual(["asset:2", "job:1"]);
    expect(changed).toHaveBeenCalledTimes(2);
    expect(onEvent).toHaveBeenLastCalledWith({ kind: "asset", data: asset({ id: 2 }) });
  });

  it("ignores malformed messages", () => {
    store.receive("job", { data: "not json" });
    store.receive("job", { data: JSON.stringify({ status: "queued" }) });
    store.receive("job", { data: "null" });
    vi.runAllTimers();
    expect(store.getSnapshot().events).toHaveLength(0);
    expect(invalidateQueries).not.toHaveBeenCalled();
  });

  it("caps the feed", () => {
    for (let i = 0; i < 100; i++) store.receive("job", { data: JSON.stringify(job({ id: i })) });
    const events = store.getSnapshot().events;
    expect(events.length).toBeLessThan(100);
    expect(events[0].data.id).toBe(99);
  });

  it("reports the stream as unsupported without EventSource and shares one connection", () => {
    vi.stubGlobal("EventSource", undefined);
    const releaseA = store.connect();
    const releaseB = store.connect();
    expect(store.getSnapshot().status).toBe("unsupported");
    releaseA();
    expect(store.getSnapshot().status).toBe("unsupported");
    releaseB();
    expect(store.getSnapshot().status).toBe("idle");
    vi.unstubAllGlobals();
  });

  describe("when the stream drops", () => {
    class FakeEventSource {
      static readonly CONNECTING = 0;
      static readonly OPEN = 1;
      static readonly CLOSED = 2;
      static instances: FakeEventSource[] = [];
      readyState = FakeEventSource.CONNECTING;
      closed = false;
      onopen: (() => void) | null = null;
      onerror: (() => void) | null = null;
      constructor(readonly url: string) {
        FakeEventSource.instances.push(this);
      }
      addEventListener() {}
      close() {
        this.closed = true;
        this.readyState = FakeEventSource.CLOSED;
      }
      open() {
        this.readyState = FakeEventSource.OPEN;
        this.onopen?.();
      }
      fail(givenUp: boolean) {
        this.readyState = givenUp ? FakeEventSource.CLOSED : FakeEventSource.CONNECTING;
        this.onerror?.();
      }
    }
    const latest = () => FakeEventSource.instances.at(-1)!;

    beforeEach(() => {
      FakeEventSource.instances = [];
      vi.stubGlobal("EventSource", FakeEventSource);
    });

    afterEach(() => vi.unstubAllGlobals());

    it("refetches what is on screen after the browser reconnects by itself", () => {
      store.connect();
      latest().open();
      latest().fail(false);
      expect(store.getSnapshot().status).toBe("reconnecting");
      expect(FakeEventSource.instances).toHaveLength(1);

      latest().open();
      expect(store.getSnapshot().status).toBe("open");
      expect(invalidateQueries).toHaveBeenCalledExactlyOnceWith();
    });

    it("reopens with backoff after the browser gives up, then catches up", () => {
      store.connect();
      latest().open();
      latest().fail(true);
      expect(latest().closed).toBe(true);
      expect(store.getSnapshot().status).toBe("reconnecting");

      vi.advanceTimersByTime(1_999);
      expect(FakeEventSource.instances).toHaveLength(1);
      vi.advanceTimersByTime(1);
      expect(FakeEventSource.instances).toHaveLength(2);
      expect(store.getSnapshot().status).toBe("reconnecting");

      latest().fail(true);
      vi.advanceTimersByTime(2_000);
      expect(FakeEventSource.instances).toHaveLength(2);
      vi.advanceTimersByTime(2_000);
      expect(FakeEventSource.instances).toHaveLength(3);
      expect(invalidateQueries).not.toHaveBeenCalled();

      latest().open();
      expect(store.getSnapshot().status).toBe("open");
      expect(invalidateQueries).toHaveBeenCalledExactlyOnceWith();

      latest().fail(true);
      vi.advanceTimersByTime(2_000);
      expect(FakeEventSource.instances).toHaveLength(4);
    });

    it("stops retrying once nothing is listening", () => {
      const release = store.connect();
      latest().fail(true);
      release();
      expect(store.getSnapshot().status).toBe("idle");
      vi.advanceTimersByTime(60_000);
      expect(FakeEventSource.instances).toHaveLength(1);

      store.connect();
      expect(FakeEventSource.instances).toHaveLength(2);
      expect(store.getSnapshot().status).toBe("connecting");
    });
  });
});
