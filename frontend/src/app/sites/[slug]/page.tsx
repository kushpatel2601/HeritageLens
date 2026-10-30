import type { Metadata } from "next";
import { Suspense } from "react";

import { SiteView } from "@/components/site/site-view";
import { Skeleton } from "@/components/ui/primitives";
import { loadSite } from "@/lib/api/server";

export async function generateMetadata({ params }: PageProps<"/sites/[slug]">): Promise<Metadata> {
  const site = await loadSite((await params).slug);
  return {
    title: site.name,
    description: site.summary,
    alternates: { canonical: `/sites/${site.slug}` },
  };
}

export default function SitePage({ params }: PageProps<"/sites/[slug]">) {
  return (
    <Suspense fallback={<SiteSkeleton />}>
      <SiteLoader params={params} />
    </Suspense>
  );
}

async function SiteLoader({ params }: Pick<PageProps<"/sites/[slug]">, "params">) {
  const site = await loadSite((await params).slug);
  return <SiteView initial={site} />;
}

function SiteSkeleton() {
  return (
    <div aria-busy="true" aria-label="Loading site">
      <div className="h-80 bg-ink/90" />
      <div className="mx-auto grid max-w-7xl gap-10 px-4 py-10 lg:grid-cols-[1fr_320px]">
        <div className="space-y-4">
          <Skeleton className="h-8 w-1/3" />
          <Skeleton className="h-24" />
          <Skeleton className="h-[420px]" />
        </div>
        <Skeleton className="h-96" />
      </div>
    </div>
  );
}
