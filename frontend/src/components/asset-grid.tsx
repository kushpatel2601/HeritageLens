import clsx from "clsx";
import Link from "next/link";

import { StatusPill } from "@/components/ui/primitives";
import { KindIcon, Thumb } from "@/components/ui/thumb";
import type { AssetBrief } from "@/lib/api/types";
import { kindLabel, langAttr, languageName } from "@/lib/format";

export function AssetTile({ asset, className }: { asset: AssetBrief; className?: string }) {
  return (
    <Link
      href={`/assets/${asset.id}`}
      className={clsx(
        "card group flex flex-col overflow-hidden transition-shadow hover:shadow-[var(--shadow-lift)]",
        className,
      )}
    >
      <div className="relative">
        <Thumb src={asset.thumb_url} alt="" kind={asset.kind} className="aspect-[4/3] w-full" />
        {asset.status !== "ready" && <StatusPill status={asset.status} className="absolute top-2 right-2 shadow" />}
      </div>
      <div className="flex flex-1 flex-col gap-1 p-3">
        <p lang={langAttr(asset.language)} className="line-clamp-2 leading-snug font-semibold group-hover:underline">
          {asset.title}
        </p>
        <p className="mt-auto flex items-center gap-1.5 text-xs text-muted">
          <KindIcon kind={asset.kind} className="size-3.5" />
          {kindLabel(asset.kind)}
          {asset.language && asset.language !== "en" && <> · {languageName(asset.language)}</>}
          {asset.site_name && <> · {asset.site_name}</>}
        </p>
      </div>
    </Link>
  );
}

export function AssetGrid({ assets, className }: { assets: AssetBrief[]; className?: string }) {
  return (
    <ul className={clsx("grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4", className)}>
      {assets.map((a) => (
        <li key={a.id} className="flex">
          <AssetTile asset={a} className="w-full" />
        </li>
      ))}
    </ul>
  );
}
