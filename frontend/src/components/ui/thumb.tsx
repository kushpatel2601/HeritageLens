"use client";

import clsx from "clsx";
import { FileText, Image as ImageIcon, Presentation, ScrollText, NotebookPen, MessageSquareQuote } from "lucide-react";
import { useState } from "react";

const KIND_ICON = {
  photo: ImageIcon,
  scan: ScrollText,
  pdf: FileText,
  deck: Presentation,
  journal: NotebookPen,
  story: MessageSquareQuote,
} as const;

/**
 * Thumbnails are already resized and cached by the API (`/assets/{id}/thumbnail`), so a plain
 * lazy <img> is cheaper than routing them through the Next image optimizer a second time.
 */
export function Thumb({
  src,
  alt,
  kind = "photo",
  className,
  eager = false,
}: {
  src: string | null | undefined;
  alt: string;
  kind?: string;
  className?: string;
  eager?: boolean;
}) {
  const [failed, setFailed] = useState(false);
  const Icon = KIND_ICON[kind as keyof typeof KIND_ICON] ?? FileText;
  if (!src || failed) {
    return (
      <div
        role="img"
        aria-label={alt}
        className={clsx("flex items-center justify-center bg-sand text-sandstone-dark", className)}
      >
        <Icon aria-hidden className="size-1/3 max-h-12 max-w-12" />
      </div>
    );
  }
  return (
    // eslint-disable-next-line @next/next/no-img-element -- API-resized image, see comment above
    <img
      src={src}
      alt={alt}
      loading={eager ? "eager" : "lazy"}
      decoding="async"
      onError={() => setFailed(true)}
      className={clsx("bg-sand object-cover", className)}
    />
  );
}

export function KindIcon({ kind, className }: { kind: string; className?: string }) {
  const Icon = KIND_ICON[kind as keyof typeof KIND_ICON] ?? FileText;
  return <Icon aria-hidden className={className} />;
}
