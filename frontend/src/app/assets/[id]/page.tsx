import type { Metadata } from "next";
import { Suspense } from "react";

import { AssetView } from "@/components/asset/asset-view";
import { Skeleton } from "@/components/ui/primitives";
import { loadAsset, loadChunks } from "@/lib/api/server";
import { kindLabel } from "@/lib/format";

export async function generateMetadata({ params }: PageProps<"/assets/[id]">): Promise<Metadata> {
  const asset = await loadAsset(Number((await params).id));
  return {
    title: asset.title,
    description: asset.caption ?? `${kindLabel(asset.kind)}${asset.site_name ? ` from ${asset.site_name}` : ""}`,
    alternates: { canonical: `/assets/${asset.id}` },
  };
}

export default function AssetPage({ params, searchParams }: PageProps<"/assets/[id]">) {
  return (
    <Suspense fallback={<AssetSkeleton />}>
      <AssetLoader params={params} searchParams={searchParams} />
    </Suspense>
  );
}

async function AssetLoader({ params, searchParams }: Pick<PageProps<"/assets/[id]">, "params" | "searchParams">) {
  const [{ id }, query] = await Promise.all([params, searchParams]);
  const assetId = Number(id);
  const [asset, chunks] = await Promise.all([loadAsset(assetId), loadChunks(assetId)]);
  const page = Number(Array.isArray(query.page) ? query.page[0] : query.page);
  return (
    <AssetView
      key={asset.id}
      initial={asset}
      initialChunks={chunks}
      initialPage={Number.isSafeInteger(page) && page > 0 ? page : 1}
    />
  );
}

function AssetSkeleton() {
  return (
    <div className="mx-auto max-w-7xl space-y-6 px-4 py-8" aria-busy="true" aria-label="Loading item">
      <Skeleton className="h-4 w-48" />
      <Skeleton className="h-10 w-2/3" />
      <div className="grid gap-10 lg:grid-cols-[1fr_340px]">
        <Skeleton className="h-[520px]" />
        <div className="space-y-4">
          <Skeleton className="h-48" />
          <Skeleton className="h-40" />
        </div>
      </div>
    </div>
  );
}
