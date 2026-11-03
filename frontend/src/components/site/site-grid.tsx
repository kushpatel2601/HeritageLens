"use client";

import { useQuery } from "@tanstack/react-query";
import { Box } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";

import { Badge, ErrorState, Skeleton } from "@/components/ui/primitives";
import { Thumb } from "@/components/ui/thumb";
import { sitesQuery } from "@/lib/api/queries";
import { categoryColor, formatEra, scriptLang, titleCase } from "@/lib/format";

export function SiteGrid() {
  const { data, error, isPending, refetch } = useQuery(sitesQuery());
  const [category, setCategory] = useState<string | null>(null);

  const categories = useMemo(() => [...new Set((data ?? []).map((s) => s.category))].sort(), [data]);
  const shown = (data ?? []).filter((s) => !category || s.category === category);

  if (error) return <ErrorState error={error} onRetry={() => void refetch()} />;
  return (
    <>
      <div role="group" aria-label="Filter by category" className="mb-6 flex flex-wrap gap-2">
        <button type="button" className="chip" aria-pressed={category === null} onClick={() => setCategory(null)}>
          All {data && <span className="text-muted">{data.length}</span>}
        </button>
        {categories.map((c) => (
          <button
            key={c}
            type="button"
            className="chip"
            aria-pressed={category === c}
            onClick={() => setCategory(category === c ? null : c)}
          >
            <span aria-hidden className="size-2 rounded-full" style={{ background: categoryColor(c) }} />
            {titleCase(c)}
          </button>
        ))}
      </div>
      <ul className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
        {isPending &&
          Array.from({ length: 6 }, (_, i) => (
            <li key={i}>
              <Skeleton className="h-80" />
            </li>
          ))}
        {shown.map((s) => (
          <li key={s.slug} data-reveal className="flex">
            <Link
              href={`/sites/${s.slug}`}
              className="card card-lift group flex w-full flex-col overflow-hidden"
            >
              <div className="relative overflow-hidden">
                <Thumb
                  src={s.cover_url}
                  alt=""
                  className="aspect-[16/10] w-full transition-transform duration-500 ease-out motion-safe:group-hover:scale-[1.04]"
                />
                <div className="absolute top-2 left-2 flex gap-1.5">
                  {s.unesco && <Badge tone="ochre">UNESCO</Badge>}
                  {s.twin_count > 0 && (
                    <Badge tone="indigo">
                      <Box aria-hidden className="size-3" /> 3D
                    </Badge>
                  )}
                </div>
              </div>
              <div className="flex flex-1 flex-col p-4">
                <p className="flex items-center gap-1.5 text-xs font-semibold text-muted uppercase">
                  <span aria-hidden className="size-2 rounded-full" style={{ background: categoryColor(s.category) }} />
                  {titleCase(s.category)} · {s.district ?? s.state}
                </p>
                <h2 className="mt-1 font-serif text-2xl leading-tight font-semibold group-hover:underline">{s.name}</h2>
                {s.name_native && (
                  <p lang={scriptLang(s.name_native)} className="text-ink-soft">
                    {s.name_native}
                  </p>
                )}
                <p className="mt-2 line-clamp-3 text-sm text-ink-soft">{s.summary}</p>
                <p className="mt-auto pt-3 text-xs text-muted">
                  {s.era_label ?? formatEra(s.era_start, s.era_end)} · {s.asset_count} items
                </p>
              </div>
            </Link>
          </li>
        ))}
      </ul>
    </>
  );
}
