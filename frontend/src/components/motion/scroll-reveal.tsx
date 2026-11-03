"use client";

import { useEffect } from "react";

import { prefersReducedMotion, revealDelay } from "@/lib/motion";

const KEYFRAMES: Keyframe[] = [
  { opacity: 0, transform: "translate3d(0, 18px, 0)" },
  { opacity: 1, transform: "translate3d(0, 0, 0)" },
];
const TIMING: KeyframeAnimationOptions = { duration: 650, easing: "cubic-bezier(0.22, 1, 0.36, 1)", fill: "backwards" };

/**
 * Fades `[data-reveal]` elements up as they scroll into view. One observer serves the whole app, so
 * any component (server or client) opts in with a single attribute.
 *
 * - Content already on screen at first paint is left alone, so nothing flashes. Content below the
 *   fold, or that arrives later (query results, route changes), is held hidden and animates in,
 *   staggered, when it enters the viewport.
 * - It drives the Web Animations API instead of writing attributes or inline styles, so it never
 *   alters server-rendered markup that React has yet to hydrate.
 * - Without JavaScript, with reduced motion, or when printing, everything stays visible.
 */
export function ScrollReveal() {
  useEffect(() => {
    if (
      prefersReducedMotion() ||
      !("IntersectionObserver" in window) ||
      typeof HTMLElement.prototype.animate !== "function"
    ) {
      return;
    }

    const seen = new WeakSet<Element>();
    const pending = new Map<Element, Animation>();

    const io = new IntersectionObserver(
      (entries) => {
        let step = 0;
        for (const entry of entries) {
          if (!entry.isIntersecting) continue;
          const animation = pending.get(entry.target);
          if (!animation) continue;
          release(entry.target);
          animation.effect?.updateTiming({ delay: revealDelay(step++) });
          animation.play();
        }
      },
      { rootMargin: "0px 0px -6% 0px", threshold: 0.06 },
    );

    const release = (el: Element) => {
      pending.delete(el);
      io.unobserve(el);
    };

    const track = (el: HTMLElement, firstPaint: boolean) => {
      if (seen.has(el)) return;
      seen.add(el);
      if (firstPaint && el.getBoundingClientRect().top < window.innerHeight) return;
      const animation = el.animate(KEYFRAMES, TIMING);
      animation.pause();
      pending.set(el, animation);
      io.observe(el);
    };

    const scan = (root: Element | Document, firstPaint: boolean) => {
      if (root instanceof HTMLElement && root.hasAttribute("data-reveal")) track(root, firstPaint);
      root.querySelectorAll<HTMLElement>("[data-reveal]").forEach((el) => track(el, firstPaint));
    };

    const forget = (root: Element) => {
      for (const [el, animation] of pending) {
        if (root.contains(el)) {
          animation.cancel();
          release(el);
        }
      }
    };

    const showAll = () => {
      for (const [el, animation] of pending) {
        animation.cancel();
        release(el);
      }
    };

    scan(document, true);
    const mo = new MutationObserver((records) => {
      for (const record of records) {
        record.removedNodes.forEach((node) => node instanceof Element && forget(node));
        record.addedNodes.forEach((node) => node instanceof HTMLElement && scan(node, false));
      }
    });
    mo.observe(document.body, { childList: true, subtree: true });
    window.addEventListener("beforeprint", showAll);

    return () => {
      window.removeEventListener("beforeprint", showAll);
      mo.disconnect();
      showAll();
      io.disconnect();
    };
  }, []);

  return null;
}
