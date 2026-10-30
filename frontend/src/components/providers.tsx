"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  createContext,
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
        // 4xx responses are answers, not outages: never retry them.
        retry: (failures, error) =>
          !(error instanceof ApiError && error.status >= 400 && error.status < 500) && failures < 2,
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
      <LiveContext.Provider value={live}>{children}</LiveContext.Provider>
    </QueryClientProvider>
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
