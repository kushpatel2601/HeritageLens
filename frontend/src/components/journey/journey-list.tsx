"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Footprints, Route } from "lucide-react";
import Link from "next/link";

import { ErrorState, Skeleton } from "@/components/ui/primitives";
import { Thumb } from "@/components/ui/thumb";
import { journeysQuery } from "@/lib/api/queries";
import { formatKm } from "@/lib/format";

export function JourneyList() {
  const { data, error, isPending, refetch } = useQuery(journeysQuery());
  if (error) return <ErrorState error={error} onRetry={() => void refetch()} />;
  return (
    <ul className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
      {isPending &&
        Array.from({ length: 3 }, (_, i) => (
          <li key={i}>
            <Skeleton className="h-96" />
          </li>
        ))}
      {data?.map((j) => (
        <li key={j.slug} className="flex">
          <Link
            href={`/journeys/${j.slug}`}
            className="card group flex w-full flex-col overflow-hidden transition-shadow hover:shadow-[var(--shadow-lift)]"
          >
            <div className="relative">
              <Thumb src={j.cover_url} alt="" className="aspect-[16/10] w-full" />
              <span aria-hidden className="absolute inset-x-0 bottom-0 h-1.5" style={{ background: j.color }} />
            </div>
            <div className="flex flex-1 flex-col p-5">
              <p className="text-xs font-semibold text-muted uppercase">
                {j.year} · {j.region ?? "India"}
              </p>
              <h2 className="mt-1 font-serif text-2xl leading-tight font-semibold group-hover:underline">{j.title}</h2>
              <p className="text-sm text-ink-soft">by {j.fellow}</p>
              <p className="mt-3 line-clamp-3 text-sm text-ink-soft">{j.summary}</p>
              <div className="mt-auto flex items-center gap-4 pt-4 text-sm text-muted">
                <span className="flex items-center gap-1">
                  <Footprints aria-hidden className="size-4" /> {j.stop_count} stops
                </span>
                <span className="flex items-center gap-1">
                  <Route aria-hidden className="size-4" /> {formatKm(j.distance_km)}
                </span>
                <ArrowRight aria-hidden className="ml-auto size-4 text-terracotta transition-transform group-hover:translate-x-1" />
              </div>
            </div>
          </Link>
        </li>
      ))}
    </ul>
  );
}
