/**
 * Scroll and motion helpers shared by the reveal-on-scroll, progress bar, back-to-top and count-up
 * components. Everything that moves checks `prefersReducedMotion()` first, and the CSS repeats the
 * check, so people who ask their OS for less motion get a static page.
 */

export const REVEAL_STAGGER_MS = 70;
export const REVEAL_MAX_STEPS = 6;

export function prefersReducedMotion(): boolean {
  return (
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

export function clamp01(n: number): number {
  if (Number.isNaN(n)) return 0;
  return Math.min(1, Math.max(0, n));
}

export function easeOutCubic(t: number): number {
  return 1 - (1 - clamp01(t)) ** 3;
}

/** Value between `from` and `to` at progress `t`; whole-number targets stay whole while counting. */
export function tween(from: number, to: number, t: number): number {
  const p = clamp01(t);
  if (p === 1) return to;
  const value = from + (to - from) * p;
  return Number.isInteger(to) ? Math.round(value) : value;
}

/** How far down the page the reader is, from 0 to 1; 0 when the page does not scroll. */
export function scrollProgress(scrollTop: number, scrollHeight: number, clientHeight: number): number {
  const range = scrollHeight - clientHeight;
  return range > 0 ? clamp01(scrollTop / range) : 0;
}

/** Items that scroll into view together fade in one after another, capped so long lists don't lag. */
export function revealDelay(index: number): number {
  return Math.min(Math.max(0, Math.floor(index)), REVEAL_MAX_STEPS) * REVEAL_STAGGER_MS;
}
