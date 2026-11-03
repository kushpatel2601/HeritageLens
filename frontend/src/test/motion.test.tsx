import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CountUp } from "@/components/motion/count-up";
import { ScrollReveal } from "@/components/motion/scroll-reveal";
import { formatNumber, formatPercent } from "@/lib/format";
import { clamp01, easeOutCubic, revealDelay, REVEAL_MAX_STEPS, REVEAL_STAGGER_MS, scrollProgress, tween } from "@/lib/motion";

function stubReducedMotion(reduce: boolean) {
  vi.stubGlobal("matchMedia", (query: string) => ({ matches: reduce && query.includes("reduce"), media: query }));
}

describe("motion helpers", () => {
  it("clamps progress into 0..1", () => {
    expect(clamp01(-0.5)).toBe(0);
    expect(clamp01(0.25)).toBe(0.25);
    expect(clamp01(7)).toBe(1);
    expect(clamp01(Number.NaN)).toBe(0);
  });

  it("eases out: fast at first, settling exactly on 1", () => {
    expect(easeOutCubic(0)).toBe(0);
    expect(easeOutCubic(0.5)).toBeCloseTo(0.875);
    expect(easeOutCubic(1)).toBe(1);
    expect(easeOutCubic(3)).toBe(1);
  });

  it("tweens whole numbers as whole numbers and lands exactly on the target", () => {
    expect(tween(0, 17, 0.5)).toBe(9);
    expect(tween(0, 0.3, 0.5)).toBeCloseTo(0.15);
    expect(tween(0, 0.3, 1)).toBe(0.3);
    expect(tween(40, 12, 1)).toBe(12);
  });

  it("measures how far down the page the reader is", () => {
    expect(scrollProgress(0, 3000, 1000)).toBe(0);
    expect(scrollProgress(1000, 3000, 1000)).toBe(0.5);
    expect(scrollProgress(2400, 3000, 1000)).toBe(1);
    expect(scrollProgress(0, 800, 1000)).toBe(0);
  });

  it("staggers reveals, capped so long lists don't lag", () => {
    expect(revealDelay(0)).toBe(0);
    expect(revealDelay(2)).toBe(2 * REVEAL_STAGGER_MS);
    expect(revealDelay(50)).toBe(REVEAL_MAX_STEPS * REVEAL_STAGGER_MS);
    expect(revealDelay(-3)).toBe(0);
  });
});

describe("<CountUp>", () => {
  let root: Root | null = null;
  let container: HTMLDivElement;

  beforeEach(() => {
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    vi.useFakeTimers({ toFake: ["requestAnimationFrame", "cancelAnimationFrame", "performance"] });
    container = document.createElement("div");
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root?.unmount());
    root = null;
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  const visible = () => container.querySelector("[aria-hidden]")?.textContent;
  const spoken = () => container.querySelector(".sr-only")?.textContent;

  it("counts up to the value while screen readers get the final number at once", () => {
    stubReducedMotion(false);
    act(() => root!.render(<CountUp value={1250} format={formatNumber} duration={500} />));
    expect(spoken()).toBe("1,250");

    act(() => vi.advanceTimersByTime(200));
    const midway = Number(visible()?.replace(/,/g, ""));
    expect(midway).toBeGreaterThan(0);
    expect(midway).toBeLessThan(1250);

    act(() => vi.advanceTimersByTime(600));
    expect(visible()).toBe("1,250");
  });

  it("glides from the old value to a new one when live stats change", () => {
    stubReducedMotion(false);
    act(() => root!.render(<CountUp value={0.5} format={formatPercent} duration={300} />));
    act(() => vi.advanceTimersByTime(400));
    expect(visible()).toBe("50%");

    act(() => root!.render(<CountUp value={0.75} format={formatPercent} duration={300} />));
    act(() => vi.advanceTimersByTime(32));
    const percent = Number(visible()?.replace("%", ""));
    expect(percent).toBeGreaterThanOrEqual(50);
    expect(percent).toBeLessThan(75);

    act(() => vi.advanceTimersByTime(400));
    expect(visible()).toBe("75%");
  });

  it("jumps straight to the value when the reader prefers reduced motion", () => {
    stubReducedMotion(true);
    act(() => root!.render(<CountUp value={17} duration={5000} />));
    act(() => vi.advanceTimersByTime(20));
    expect(visible()).toBe("17");
  });
});

type FakeAnimation = { state: "paused" | "running" | "cancelled"; delay: number };

describe("<ScrollReveal>", () => {
  let root: Root | null = null;
  let page: HTMLDivElement;
  let observed: Set<Element>;
  let animations: Map<Element, FakeAnimation>;
  let fire: (targets: Element[]) => void;
  const realAnimate = HTMLElement.prototype.animate;

  const item = (top: number) => {
    const el = document.createElement("div");
    el.setAttribute("data-reveal", "");
    el.getBoundingClientRect = () => ({ top }) as DOMRect;
    return el;
  };

  beforeEach(() => {
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    observed = new Set();
    vi.stubGlobal(
      "IntersectionObserver",
      class {
        constructor(callback: IntersectionObserverCallback) {
          fire = (targets) =>
            callback(
              targets.map((target) => ({ target, isIntersecting: true }) as IntersectionObserverEntry),
              this as unknown as IntersectionObserver,
            );
        }
        observe = (el: Element) => observed.add(el);
        unobserve = (el: Element) => observed.delete(el);
        disconnect = () => observed.clear();
      },
    );
    animations = new Map();
    HTMLElement.prototype.animate = function (this: HTMLElement) {
      const fake: FakeAnimation = { state: "running", delay: 0 };
      animations.set(this, fake);
      return {
        pause: () => void (fake.state = "paused"),
        play: () => void (fake.state = "running"),
        cancel: () => void (fake.state = "cancelled"),
        effect: { updateTiming: ({ delay }: OptionalEffectTiming) => void (fake.delay = Number(delay ?? 0)) },
      } as unknown as Animation;
    };
    page = document.createElement("div");
    document.body.append(page);
  });

  afterEach(() => {
    act(() => root?.unmount());
    root = null;
    page.remove();
    HTMLElement.prototype.animate = realAnimate;
    vi.unstubAllGlobals();
  });

  const mount = () => {
    const host = document.createElement("div");
    root = createRoot(host);
    act(() => root!.render(<ScrollReveal />));
  };

  it("leaves on-screen content alone and hides what is below the fold until it scrolls in", () => {
    stubReducedMotion(false);
    const onScreen = item(120);
    const belowFold = item(window.innerHeight + 400);
    page.append(onScreen, belowFold);
    mount();

    expect(animations.has(onScreen)).toBe(false);
    expect(animations.get(belowFold)?.state).toBe("paused");
    expect([...observed]).toEqual([belowFold]);
    // Server-rendered markup is never touched, so hydration can't mismatch.
    expect(belowFold.getAttributeNames()).toEqual(["data-reveal"]);

    fire([belowFold]);
    expect(animations.get(belowFold)?.state).toBe("running");
    expect(observed.size).toBe(0);
  });

  it("animates content that arrives later, staggering items that enter together", async () => {
    stubReducedMotion(false);
    mount();
    const first = item(100);
    const second = item(300);
    await act(async () => page.append(first, second));

    expect(animations.get(first)?.state).toBe("paused");
    expect(animations.get(second)?.state).toBe("paused");

    fire([first, second]);
    expect(animations.get(first)).toEqual({ state: "running", delay: 0 });
    expect(animations.get(second)).toEqual({ state: "running", delay: REVEAL_STAGGER_MS });
  });

  it("stops watching items that are removed before they are seen", async () => {
    stubReducedMotion(false);
    mount();
    const later = item(5000);
    await act(async () => page.append(later));
    expect(observed.has(later)).toBe(true);

    await act(async () => later.remove());
    expect(observed.has(later)).toBe(false);
    expect(animations.get(later)?.state).toBe("cancelled");
  });

  it("shows anything still hidden when the page is printed", () => {
    stubReducedMotion(false);
    const belowFold = item(window.innerHeight + 400);
    page.append(belowFold);
    mount();

    act(() => window.dispatchEvent(new Event("beforeprint")));
    expect(animations.get(belowFold)?.state).toBe("cancelled");
    expect(observed.size).toBe(0);
  });

  it("does nothing when the reader prefers reduced motion", () => {
    stubReducedMotion(true);
    const belowFold = item(window.innerHeight + 400);
    page.append(belowFold);
    mount();

    expect(animations.size).toBe(0);
    expect(observed.size).toBe(0);
  });
});
