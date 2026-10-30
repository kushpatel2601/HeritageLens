"use client";

import clsx from "clsx";
import { Search } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { useLive } from "@/components/providers";

export const NAV = [
  { href: "/", label: "Atlas" },
  { href: "/search", label: "Search" },
  { href: "/sites", label: "Sites" },
  { href: "/journeys", label: "Journeys" },
  { href: "/archive", label: "Archive" },
  { href: "/contribute", label: "Contribute" },
] as const;

function isActive(pathname: string, href: string): boolean {
  return href === "/" ? pathname === "/" : pathname === href || pathname.startsWith(`${href}/`);
}

export function NavLinks({ className }: { className?: string }) {
  const pathname = usePathname();
  return <NavList className={className} pathname={pathname} />;
}

/** Rendered in the static shell while the pathname is not yet known. */
export function NavList({ className, pathname }: { className?: string; pathname?: string }) {
  return (
    <ul className={clsx("flex items-center gap-1", className)}>
      {NAV.map(({ href, label }) => {
        const active = pathname !== undefined && isActive(pathname, href);
        return (
          <li key={href}>
            <Link
              href={href}
              aria-current={active ? "page" : undefined}
              className={clsx(
                "rounded-full px-3 py-1.5 text-sm font-semibold transition-colors",
                active ? "bg-white/15 text-white" : "text-white/80 hover:bg-white/10 hover:text-white",
              )}
            >
              {label}
            </Link>
          </li>
        );
      })}
    </ul>
  );
}

const LIVE_LABEL = {
  open: "Live updates on",
  connecting: "Connecting to live updates",
  reconnecting: "Reconnecting to live updates",
  idle: "Live updates paused",
  unsupported: "Live updates unavailable in this browser",
} as const;

export function LiveIndicator() {
  const { status } = useLive();
  const label = LIVE_LABEL[status];
  return (
    <span className="flex items-center gap-1.5 text-xs font-semibold text-white/80" title={label}>
      <span
        aria-hidden
        className={clsx(
          "size-2 rounded-full",
          status === "open" ? "animate-pulse-dot bg-emerald-400" : status === "idle" ? "bg-white/40" : "bg-amber-300",
        )}
      />
      <span className="sr-only sm:not-sr-only">{status === "open" ? "Live" : "Offline"}</span>
      <span className="sr-only">{label}</span>
    </span>
  );
}

export function HeaderSearch() {
  const router = useRouter();
  const [q, setQ] = useState("");
  const submit = (e: FormEvent) => {
    e.preventDefault();
    const query = q.trim();
    if (query) router.push(`/search?q=${encodeURIComponent(query)}`);
  };
  return (
    <form role="search" onSubmit={submit} className="relative hidden md:block">
      <label htmlFor="header-search" className="sr-only">
        Search the archive
      </label>
      <Search aria-hidden className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-white/60" />
      <input
        id="header-search"
        type="search"
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder="રાણી કી વાવ, stepwell, 1063…"
        className="w-64 rounded-full border border-white/20 bg-white/10 py-1.5 pr-3 pl-9 text-sm text-white placeholder:text-white/50 focus:bg-white/15 lg:w-72"
      />
    </form>
  );
}
