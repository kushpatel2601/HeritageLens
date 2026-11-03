"use client";

import clsx from "clsx";
import { ArrowUp } from "lucide-react";
import { useEffect, useState } from "react";

import { prefersReducedMotion } from "@/lib/motion";

/**
 * Floating "back to top" button that appears once the reader is more than a screen and a bit down
 * the page. While hidden it is `inert`, so it never takes keyboard focus; if it is focused when it
 * hides, the browser returns focus to the top of the document. It sits above the bottom-right
 * corner so it never covers map attribution controls.
 */
export function BackToTop({ after = 1.2 }: { after?: number }) {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    let frame = 0;
    const update = () => {
      frame = 0;
      setVisible(window.scrollY > window.innerHeight * after);
    };
    const schedule = () => {
      if (!frame) frame = requestAnimationFrame(update);
    };

    schedule();
    window.addEventListener("scroll", schedule, { passive: true });
    window.addEventListener("resize", schedule, { passive: true });
    return () => {
      window.removeEventListener("scroll", schedule);
      window.removeEventListener("resize", schedule);
      cancelAnimationFrame(frame);
    };
  }, [after]);

  return (
    <button
      type="button"
      aria-label="Back to top"
      title="Back to top"
      inert={!visible}
      onClick={() => window.scrollTo({ top: 0, behavior: prefersReducedMotion() ? "instant" : "smooth" })}
      className={clsx(
        "fixed right-4 bottom-14 z-30 grid size-11 place-items-center rounded-full border border-white/20 bg-indigo-ink text-white shadow-[var(--shadow-lift)] transition-[opacity,transform,background-color] duration-300 hover:bg-indigo-ink-dark print:hidden sm:right-6",
        visible ? "translate-y-0 opacity-100" : "pointer-events-none translate-y-3 opacity-0",
      )}
    >
      <ArrowUp aria-hidden className="size-5" />
    </button>
  );
}
