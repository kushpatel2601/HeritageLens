import { Compass } from "lucide-react";
import Link from "next/link";

export default function NotFound() {
  return (
    <div className="mx-auto flex max-w-xl flex-1 flex-col items-center justify-center gap-4 px-4 py-20 text-center">
      <Compass aria-hidden className="size-12 text-terracotta" />
      <h1 className="text-4xl font-semibold">Not in the archive</h1>
      <p className="text-muted">
        We couldn&apos;t find that page. The record may have been removed, or the link may be mistyped.
      </p>
      <div className="flex flex-wrap justify-center gap-3">
        <Link href="/" className="btn btn-primary">
          Back to the atlas
        </Link>
        <Link href="/search" className="btn btn-secondary">
          Search the archive
        </Link>
      </div>
    </div>
  );
}
