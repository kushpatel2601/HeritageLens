import type { Metadata } from "next";

import { SiteGrid } from "@/components/site/site-grid";

export const metadata: Metadata = {
  title: "Heritage sites",
  description: "Stepwells, temples, forts and craft clusters documented in the field archive.",
};

export default function SitesPage() {
  return (
    <div className="mx-auto w-full max-w-7xl px-4 py-10">
      <p className="eyebrow mb-1">Gazetteer</p>
      <h1 className="mb-2 text-4xl font-semibold">Heritage sites</h1>
      <p className="mb-6 max-w-2xl text-ink-soft">
        Every monument and craft cluster the field teams documented, with the notes, photographs and 3D models
        gathered there.
      </p>
      <SiteGrid />
    </div>
  );
}
