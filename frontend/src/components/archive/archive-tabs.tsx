"use client";

import { Activity, LayoutGrid } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

const TABS = [
  { href: "/archive", label: "Items", icon: LayoutGrid },
  { href: "/archive/pipeline", label: "Pipeline", icon: Activity },
] as const;

export function ArchiveTabs() {
  const pathname = usePathname();
  return (
    <nav aria-label="Archive sections" className="flex gap-1 border-b border-sandstone">
      {TABS.map(({ href, label, icon: Icon }) => {
        const active = pathname === href;
        return (
          <Link
            key={href}
            href={href}
            aria-current={active ? "page" : undefined}
            className={
              active
                ? "-mb-px flex items-center gap-2 border-b-2 border-terracotta px-4 py-2.5 text-sm font-semibold text-ink"
                : "-mb-px flex items-center gap-2 border-b-2 border-transparent px-4 py-2.5 text-sm text-muted hover:text-ink"
            }
          >
            <Icon aria-hidden className="size-4" />
            {label}
          </Link>
        );
      })}
    </nav>
  );
}
