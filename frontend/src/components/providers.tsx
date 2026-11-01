"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { LoaderCircle } from "lucide-react";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useEffectEvent,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from "react";

import { ApiError } from "@/lib/api/client";
import type { LiveEvent } from "@/lib/api/types";
import { LiveStore, type LiveSnapshot } from "@/lib/live";

let browserQueryClient: QueryClient | undefined;

function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 15_000,
        refetchOnWindowFocus: false,
        retry: (failures, error) => {
          if (error instanceof ApiError) {
            // The free API host sleeps when idle and takes up to a minute to wake: keep trying (~80 s).
            if (error.isUnavailable) return failures < 12;
            // 4xx responses are answers, not outages: never retry them.
            if (error.status >= 400 && error.status < 500) return false;
          }
          return failures < 2;
        },
        retryDelay: (attempt) => Math.min(1000 * 2 ** attempt, 8_000),
      },
    },
  });
}

function getQueryClient(): QueryClient {
  if (typeof window === "undefined") return makeQueryClient();
  browserQueryClient ??= makeQueryClient();
  return browserQueryClient;
}

const LiveContext = createContext<LiveStore | null>(null);

export function Providers({ children }: { children: ReactNode }) {
  const queryClient = getQueryClient();
  const [live] = useState(() => new LiveStore(queryClient));

  useEffect(() => live.connect(), [live]);

  return (
    <QueryClientProvider client={queryClient}>
      <LiveContext.Provider value={live}>
        {children}
        <WakingNotice client={queryClient} />
      </LiveContext.Provider>
    </QueryClientProvider>
  );
}

/** True while any query is retrying because the API host is asleep or restarting. */
function isWaking(client: QueryClient): boolean {
  return client
    .getQueryCache()
    .getAll()
    .some(
      ({ state }) =>
        state.fetchStatus === "fetching" &&
        state.fetchFailureReason instanceof ApiError &&
        state.fetchFailureReason.isUnavailable,
    );
}

function WakingNotice({ client }: { client: QueryClient }) {
  const subscribe = useCallback((onChange: () => void) => client.getQueryCache().subscribe(onChange), [client]);
  const waking = useSyncExternalStore(subscribe, () => isWaking(client), () => false);
  if (!waking) return null;
  return (
    <div
      role="status"
      className="fixed inset-x-4 bottom-4 z-50 mx-auto flex max-w-md items-center gap-3 rounded-[var(--radius-card)] border border-sandstone bg-white p-4 text-sm text-ink-soft shadow-[var(--shadow-card)]"
    >
      <LoaderCircle aria-hidden className="size-5 shrink-0 animate-spin text-terracotta motion-reduce:animate-none" />
      <span>
        <strong className="block text-ink">Waking the archive server…</strong>
        The free server sleeps when idle and can take up to a minute to start. This page will load on its own.
      </span>
    </div>
  );
}

function useLiveStore(): LiveStore {
  const store = useContext(LiveContext);
  if (!store) throw new Error("useLive* hooks must be used inside <Providers>");
  return store;
}

export function useLive(): LiveSnapshot {
  const store = useLiveStore();
  return useSyncExternalStore(store.subscribe, store.getSnapshot, store.getServerSnapshot);
}

/** Run `handler` for every pipeline event (e.g. to update an upload row in place). */
export function useLiveEvent(handler: (event: LiveEvent) => void): void {
  const store = useLiveStore();
  const onEvent = useEffectEvent(handler);
  useEffect(() => store.onEvent((event) => onEvent(event)), [store]);
}
