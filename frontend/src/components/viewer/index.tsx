"use client";

import dynamic from "next/dynamic";

import { Skeleton } from "@/components/ui/primitives";

import { VIEWER_HEIGHT } from "./twin-viewer-height";

/** three.js + R3F (~600 kB) only load when a page actually shows a model. */
export const TwinViewer = dynamic(() => import("./twin-viewer"), {
  ssr: false,
  loading: () => <Skeleton className={`${VIEWER_HEIGHT} w-full rounded-[var(--radius-card)]`} />,
});
