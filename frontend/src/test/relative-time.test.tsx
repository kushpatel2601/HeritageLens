import { act } from "react";
import { hydrateRoot, type Root } from "react-dom/client";
import { renderToString } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { RelativeTime } from "@/components/ui/relative-time";

const FINISHED = "2026-10-29T16:47:52Z";

describe("<RelativeTime>", () => {
  let root: Root | null = null;

  beforeEach(() => {
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    vi.useFakeTimers({ now: new Date("2026-10-31T06:25:00Z") });
  });

  afterEach(() => {
    act(() => root?.unmount());
    root = null;
    vi.useRealTimers();
  });

  it("prints the calendar date on the server, so cached HTML never goes stale", () => {
    const html = renderToString(<RelativeTime iso={FINISHED} />);
    expect(html).toBe(`<time dateTime="${FINISHED}" title="29 Oct 2026">29 Oct 2026</time>`);
  });

  it("hydrates cached HTML without a mismatch, then shows and refreshes the relative time", () => {
    const container = document.createElement("div");
    // Rendered hours earlier, as an edge-cached prerender would have been.
    vi.setSystemTime(new Date("2026-10-30T10:00:00Z"));
    container.innerHTML = renderToString(<RelativeTime iso={FINISHED} />);
    vi.setSystemTime(new Date("2026-10-31T06:25:00Z"));

    const onRecoverableError = vi.fn();
    act(() => {
      root = hydrateRoot(container, <RelativeTime iso={FINISHED} />, { onRecoverableError });
    });
    expect(onRecoverableError).not.toHaveBeenCalled();
    expect(container.textContent).toBe("2 days ago");

    vi.setSystemTime(new Date("2026-11-01T06:25:00Z"));
    act(() => vi.advanceTimersByTime(15_000));
    expect(container.textContent).toBe("3 days ago");
  });

  it("renders a dash when there is no timestamp", () => {
    expect(renderToString(<RelativeTime iso={null} />)).toBe("—");
  });
});
