import clsx from "clsx";

import { splitHighlights } from "@/lib/format";
import type { Snippet } from "@/lib/api/types";

/** Renders a backend snippet with its highlight offsets as <mark>, preserving line breaks. */
export function Highlighted({ snippet, lang, className }: { snippet: Snippet; lang?: string; className?: string }) {
  const segments = splitHighlights(snippet.text, snippet.highlights ?? []);
  return (
    <p lang={lang} className={clsx("whitespace-pre-line", className)}>
      {snippet.prefix_ellipsis && "… "}
      {segments.map((s, i) => (s.mark ? <mark key={i}>{s.text}</mark> : <span key={i}>{s.text}</span>))}
      {snippet.suffix_ellipsis && " …"}
    </p>
  );
}
