import type { Metadata } from "next";
import { Suspense } from "react";

import { SearchSkeleton, SearchView } from "@/components/search/search-view";

export const metadata: Metadata = {
  title: "Search",
  description: "Search handwritten notes, journals and photographs in Gujarati, Hindi, Sanskrit and English.",
};

/** The search UI reads its state from the URL (`?q=&lang=&kind=&page=`), so it renders at request time. */
export default function SearchPage() {
  return (
    <Suspense fallback={<SearchSkeleton />}>
      <SearchView />
    </Suspense>
  );
}
