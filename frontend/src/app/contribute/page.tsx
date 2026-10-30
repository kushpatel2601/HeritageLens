import type { Metadata } from "next";

import { ContributeForm } from "@/components/contribute/contribute-form";

export const metadata: Metadata = {
  title: "Contribute",
  description: "Upload photographs, scanned notebooks, journals and slide decks from heritage field work.",
};

export default function ContributePage() {
  return (
    <div className="mx-auto w-full max-w-7xl px-4 py-8">
      <header className="mb-8 max-w-3xl">
        <p className="eyebrow mb-1">Contribute</p>
        <h1 className="text-3xl font-semibold sm:text-4xl">Add field work to the archive</h1>
        <p className="mt-3 text-ink-soft">
          Photographs, scanned notebooks in any script, typed journals, PDFs and slide decks are all welcome. Each file
          is read, translated, linked to the places it mentions and made searchable within minutes.
        </p>
      </header>
      <ContributeForm />
    </div>
  );
}
