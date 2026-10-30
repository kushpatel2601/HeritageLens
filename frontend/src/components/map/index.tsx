"use client";

import dynamic from "next/dynamic";

import { Skeleton } from "@/components/ui/primitives";

export type { AtlasMapProps, MapFocus, StopMarker } from "./atlas-map";

/** MapLibre touches `window` at import time, so it is client-only and code-split from the shell. */
export const AtlasMap = dynamic(() => import("./atlas-map"), {
  ssr: false,
  loading: () => <Skeleton className="size-full rounded-none" />,
});
