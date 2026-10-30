import type { Metadata } from "next";

import { JourneyList } from "@/components/journey/journey-list";

export const metadata: Metadata = {
  title: "Field journeys",
  description: "Follow IKS fellows' expedition routes stop by stop, with their notes and photographs on the map.",
};

export default function JourneysPage() {
  return (
    <div className="mx-auto w-full max-w-7xl px-4 py-10">
      <p className="eyebrow mb-1">Expeditions</p>
      <h1 className="mb-2 text-4xl font-semibold">Field journeys</h1>
      <p className="mb-8 max-w-2xl text-ink-soft">
        Each journey retraces a fellow&apos;s route as a story: the map follows along as you read their field notes,
        stop by stop.
      </p>
      <JourneyList />
    </div>
  );
}
