import type { Metadata, Viewport } from "next";
import { Atkinson_Hyperlegible, Crimson_Pro, Noto_Sans_Devanagari, Noto_Sans_Gujarati } from "next/font/google";
import Link from "next/link";
import { Suspense } from "react";

import { BackToTop } from "@/components/motion/back-to-top";
import { ScrollProgress } from "@/components/motion/scroll-progress";
import { ScrollReveal } from "@/components/motion/scroll-reveal";
import { HeaderSearch, LiveIndicator, NavLinks, NavList } from "@/components/nav";
import { Providers } from "@/components/providers";

import "./globals.css";

const crimson = Crimson_Pro({ subsets: ["latin"], variable: "--font-crimson", weight: ["500", "600", "700"] });
const atkinson = Atkinson_Hyperlegible({ subsets: ["latin"], variable: "--font-atkinson", weight: ["400", "700"] });
const notoGujarati = Noto_Sans_Gujarati({
  subsets: ["gujarati"],
  variable: "--font-noto-gujarati",
  weight: ["400", "600"],
  preload: false,
});
const notoDevanagari = Noto_Sans_Devanagari({
  subsets: ["devanagari"],
  variable: "--font-noto-devanagari",
  weight: ["400", "600"],
  preload: false,
});

export const metadata: Metadata = {
  title: { default: "HeritageLens — India's living heritage archive", template: "%s · HeritageLens" },
  description:
    "Searchable, mapped and translated archive of Indian Knowledge Systems field research: stepwells, temples and crafts — handwritten notes read by AI, routes on an interactive atlas, and 3D digital twins.",
  applicationName: "HeritageLens",
};

export const viewport: Viewport = { themeColor: "#1e3a5f", width: "device-width", initialScale: 1 };

function Logo() {
  return (
    <Link href="/" className="flex items-center gap-2 text-white" aria-label="HeritageLens home">
      <svg viewBox="0 0 32 32" aria-hidden className="size-8">
        <rect width="32" height="32" rx="8" fill="#9a3412" />
        {/* stepwell section: descending terraces into water */}
        <path d="M5 9h22v3H5zM8 13h16v3H8zM11 17h10v3H11z" fill="#fbecd5" />
        <path d="M13 21h6v4h-6z" fill="#7dd3fc" />
      </svg>
      <span className="font-serif text-xl font-semibold tracking-tight">HeritageLens</span>
    </Link>
  );
}

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      data-scroll-behavior="smooth"
      className={`${crimson.variable} ${atkinson.variable} ${notoGujarati.variable} ${notoDevanagari.variable} h-full antialiased`}
    >
      <body className="flex min-h-full flex-col">
        <a
          href="#main"
          className="sr-only z-50 rounded bg-white px-3 py-2 font-semibold text-ink focus:not-sr-only focus:fixed focus:top-2 focus:left-2"
        >
          Skip to content
        </a>
        <Providers>
          <header className="jali site-header sticky top-0 z-40 shadow-md">
            <div className="mx-auto flex max-w-7xl items-center gap-4 px-4 py-2.5">
              <Logo />
              <nav aria-label="Primary" className="ml-2 hidden lg:block">
                <Suspense fallback={<NavList />}>
                  <NavLinks />
                </Suspense>
              </nav>
              <div className="ml-auto flex items-center gap-4">
                <HeaderSearch />
                <LiveIndicator />
              </div>
            </div>
            <nav aria-label="Primary (compact)" className="scrollbar-none overflow-x-auto border-t border-white/10 px-2 py-1.5 lg:hidden">
              <Suspense fallback={<NavList className="w-max" />}>
                <NavLinks className="w-max" />
              </Suspense>
            </nav>
            <ScrollProgress />
          </header>
          <main id="main" className="flex flex-1 flex-col">
            {children}
          </main>
          <footer className="border-t border-sandstone bg-sand">
            {/* Extra room on the bottom (mobile) and right (desktop) keeps the credits clear of the back-to-top button. */}
            <div className="mx-auto flex max-w-7xl flex-col gap-2 px-4 pt-6 pb-28 text-sm text-muted md:flex-row md:justify-between md:pr-20 md:pb-6">
              <p>
                <span className="font-serif text-base font-semibold text-ink">HeritageLens</span> — built for HackCult
                ’26 (HC26-CULT01) · Indian Knowledge Systems field archives.
              </p>
              <p>
                Photographs: Wikimedia Commons contributors (CC BY / CC BY-SA, credited per item). Basemap ©
                OpenStreetMap contributors.
              </p>
            </div>
          </footer>
          <BackToTop />
          <ScrollReveal />
        </Providers>
      </body>
    </html>
  );
}
