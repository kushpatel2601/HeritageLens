"use client";

import { useQuery } from "@tanstack/react-query";

import { CountUp } from "@/components/motion/count-up";
import { Skeleton, Stat } from "@/components/ui/primitives";
import { statsQuery } from "@/lib/api/queries";
import { formatNumber, formatPercent } from "@/lib/format";

/** Headline numbers that update live as the OCR / translation pipeline works through the queue. */
export function StatsBand() {
  const { data, isError } = useQuery(statsQuery());
  if (isError) return null;
  if (!data) {
    return (
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-6" aria-hidden>
        {Array.from({ length: 6 }, (_, i) => (
          <Skeleton key={i} className="h-14" />
        ))}
      </div>
    );
  }
  const languages = Object.keys(data.languages).filter((l) => l !== "und").length;
  return (
    <dl className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-6">
      <Stat
        label="Heritage sites"
        value={<CountUp value={data.sites} format={formatNumber} />}
        hint={`${data.journeys} field journeys`}
      />
      <Stat
        label="Archive items"
        value={<CountUp value={data.assets} format={formatNumber} />}
        hint={`${formatNumber(data.geotagged_assets)} on the map`}
      />
      <Stat
        label="Pages read"
        value={<CountUp value={data.pages} format={formatNumber} />}
        hint={`${formatNumber(data.ocr_pages)} by OCR`}
      />
      <Stat
        label="Translated"
        value={<CountUp value={data.chunks ? data.translated_chunks / data.chunks : 0} format={formatPercent} />}
        hint={`${formatNumber(data.translated_chunks)} of ${formatNumber(data.chunks)} passages`}
      />
      <Stat label="Languages" value={<CountUp value={languages} />} hint={`${formatNumber(data.entities)} places & dates found`} />
      <Stat
        label="Digital twins"
        value={<CountUp value={data.twins} format={formatNumber} />}
        hint={`${data.workers_online} pipeline ${data.workers_online === 1 ? "worker" : "workers"} online`}
      />
    </dl>
  );
}
