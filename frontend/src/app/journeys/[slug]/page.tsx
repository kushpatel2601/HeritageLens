import type { Metadata } from "next";
import { Suspense } from "react";

import { JourneyStory } from "@/components/journey/journey-story";
import { Skeleton } from "@/components/ui/primitives";
import { loadJourney } from "@/lib/api/server";

export async function generateMetadata({ params }: PageProps<"/journeys/[slug]">): Promise<Metadata> {
  const journey = await loadJourney((await params).slug);
  return {
    title: journey.title,
    description: journey.summary,
    alternates: { canonical: `/journeys/${journey.slug}` },
  };
}

export default function JourneyPage({ params }: PageProps<"/journeys/[slug]">) {
  return (
    <Suspense fallback={<JourneySkeleton />}>
      <JourneyLoader params={params} />
    </Suspense>
  );
}

async function JourneyLoader({ params }: Pick<PageProps<"/journeys/[slug]">, "params">) {
  const journey = await loadJourney((await params).slug);
  return <JourneyStory initial={journey} />;
}

function JourneySkeleton() {
  return (
    <div aria-busy="true" aria-label="Loading journey" className="grid lg:grid-cols-2">
      <div className="space-y-4 p-10">
        <Skeleton className="h-10 w-2/3" />
        <Skeleton className="h-24" />
        <Skeleton className="h-64" />
      </div>
      <Skeleton className="h-[60vh] rounded-none lg:h-[calc(100dvh-60px)]" />
    </div>
  );
}
