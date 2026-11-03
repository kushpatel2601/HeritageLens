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
              <a href="#demo" className="btn btn-ghost">
                Watch the demo
              </a>
            </div>
          </div>
          <StatsBand />
        </div>
      </section>
      <AtlasExplorer />
      <section id="demo" className="scroll-mt-20 border-t border-sandstone bg-sand/40">
        <div className="mx-auto max-w-5xl px-4 py-12">
          <p className="eyebrow mb-2">Demo · 3 minutes</p>
          <h2 className="text-3xl font-semibold text-balance">See HeritageLens in action</h2>
          <p className="mt-2 max-w-2xl text-ink-soft">
            Multilingual search, the side-by-side reader, the atlas and field journeys, 3D twins, contributions and the
            live GPU pipeline, narrated end to end.
          </p>
          <video
            className="card mt-6 aspect-video w-full overflow-hidden bg-ink p-0"
            controls
            playsInline
            preload="none"
            poster="/demo/heritagelens-demo-poster.jpg"
          >
            <source src="/demo/heritagelens-demo.mp4" type="video/mp4" />
            <a href="/demo/heritagelens-demo.mp4">Download the demo video</a>
          </video>
          <p className="mt-3 text-sm text-ink-soft">
            Also on{" "}
            <a
              href="https://youtu.be/xtlPzkm7XPE"
              className="text-indigo-ink underline"
              target="_blank"
              rel="noopener noreferrer"
            >
              YouTube<span className="sr-only"> (opens in a new tab)</span>
            </a>
            .
          </p>
        </div>
      </section>
    </>
  );
}
