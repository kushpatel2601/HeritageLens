import type { Metadata } from "next";
import { Suspense } from "react";

import { ArchiveBrowser, ArchiveSkeleton } from "@/components/archive/archive-browser";

export const metadata: Metadata = {
  title: "Archive",
  description: "Browse every photograph, scanned notebook, journal and deck in the archive.",
};

export default function ArchivePage() {
  return (
    <Suspense fallback={<ArchiveSkeleton />}>
      <ArchiveBrowser />
    </Suspense>
  );
}
