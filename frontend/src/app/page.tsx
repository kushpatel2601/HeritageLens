import Link from "next/link";

import { AtlasExplorer } from "@/components/atlas/explorer";
import { StatsBand } from "@/components/stats-band";

export default function AtlasPage() {
  return (
    <>
      <section className="border-b border-sandstone bg-gradient-to-b from-sand to-parchment">
        <div className="mx-auto grid max-w-7xl gap-6 px-4 py-8 lg:grid-cols-[1.1fr_1fr] lg:items-end">
          <div>
            <p className="eyebrow mb-2">Indian Knowledge Systems · Field archive</p>
            <h1 className="text-4xl leading-[1.05] font-semibold text-balance sm:text-5xl">
              Field notes, photographs and journals, <span className="text-terracotta">read, mapped and rebuilt</span>.
            </h1>
            <p className="mt-3 max-w-2xl text-lg text-ink-soft">
              HeritageLens reads handwritten Gujarati, Hindi and Sanskrit notes with OCR, translates them, pins every
              place they mention to the atlas, and turns site photographs into explorable 3D digital twins.
            </p>
            <div className="mt-4 flex flex-wrap gap-3">
              <Link href="/search?q=stepwell" className="btn btn-primary">
                Try a search
              </Link>
              <Link href="/journeys" className="btn btn-secondary">
                Follow a field journey
              </Link>
            </div>
          </div>
          <StatsBand />
        </div>
      </section>
      <AtlasExplorer />
    </>
  );
}
