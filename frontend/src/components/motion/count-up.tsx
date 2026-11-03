"use client";

import { useEffect, useRef, useState } from "react";

import { easeOutCubic, prefersReducedMotion, tween } from "@/lib/motion";

/**
 * A number that counts up to `value`, and glides to each new value when live stats change.
 * Screen readers get the final value straight away; only the visible digits animate.
 */
export function CountUp({
  value,
  format = String,
  duration = 1100,
}: {
  value: number;
  format?: (n: number) => string;
  duration?: number;
}) {
  const [shown, setShown] = useState(0);
  const current = useRef(0);

  useEffect(() => {
    const from = current.current;
    if (from === value) return;
    let frame = 0;
    let start: number | undefined;
    const step = (now: number) => {
      start ??= now;
      const t = prefersReducedMotion() || duration <= 0 ? 1 : (now - start) / duration;
      const next = tween(from, value, easeOutCubic(t));
      current.current = next;
      setShown(next);
      if (t < 1) frame = requestAnimationFrame(step);
    };
    frame = requestAnimationFrame(step);
    return () => cancelAnimationFrame(frame);
  }, [value, duration]);

  return (
    <>
      <span aria-hidden>{format(shown)}</span>
      <span className="sr-only">{format(value)}</span>
    </>
  );
}
