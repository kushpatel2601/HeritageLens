"use client";

import { useEffect, useRef } from "react";

import { scrollProgress } from "@/lib/motion";

/**
 * Thin reading-progress bar along the bottom of the sticky header. It also marks `<html>` with
 * `data-scrolled` once the page moves, which deepens the header shadow (see globals.css).
 * Updates are batched to one per animation frame and only touch a CSS variable, so scrolling stays smooth.
 */
export function ScrollProgress() {
  const bar = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const root = document.documentElement;
    let frame = 0;
    const update = () => {
      frame = 0;
      const progress = scrollProgress(root.scrollTop, root.scrollHeight, root.clientHeight);
      bar.current?.style.setProperty("--progress", progress.toFixed(4));
      root.toggleAttribute("data-scrolled", root.scrollTop > 4);
    };
    const schedule = () => {
      if (!frame) frame = requestAnimationFrame(update);
    };

    update();
    window.addEventListener("scroll", schedule, { passive: true });
    window.addEventListener("resize", schedule, { passive: true });
    // Pages grow as query results arrive, which changes progress without any scrolling.
    const resize = "ResizeObserver" in window ? new ResizeObserver(schedule) : null;
    resize?.observe(document.body);

    return () => {
      window.removeEventListener("scroll", schedule);
      window.removeEventListener("resize", schedule);
      resize?.disconnect();
      cancelAnimationFrame(frame);
      root.removeAttribute("data-scrolled");
    };
  }, []);

  return <div ref={bar} aria-hidden className="scroll-progress" />;
}
