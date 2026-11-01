import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, getJSON, toProblem, unwrap, UNREACHABLE_PROBLEM, WAKING_PROBLEM } from "@/lib/api/client";

const HTML_PAGE = "<!DOCTYPE html><html><head><style>@font-face{src:url(data:font/woff2;base64,AAAA)}</style></head></html>";

describe("toProblem", () => {
  it("passes RFC 7807 bodies through", () => {
    const problem = { title: "Not found", status: 404, detail: "No such site" };
    expect(toProblem(404, problem)).toBe(problem);
    expect(toProblem(503, { title: "Not ready" })).toEqual({ title: "Not ready" });
  });

  it("never exposes hosting error pages", () => {
    expect(toProblem(502, HTML_PAGE)).toBe(WAKING_PROBLEM);
    expect(toProblem(404, `  ${HTML_PAGE}`)).toBe(WAKING_PROBLEM);
    expect(toProblem(503, null)).toBe(WAKING_PROBLEM);
    expect(toProblem(504, { message: "gateway timeout" })).toBe(WAKING_PROBLEM);
  });

  it("keeps short plain-text bodies and truncates long ones", () => {
    expect(toProblem(500, "boom")).toEqual({ detail: "boom" });
    const detail = toProblem(500, "x".repeat(1000)).detail as string;
    expect(detail).toHaveLength(301);
    expect(toProblem(500, undefined)).toEqual({});
  });
});

describe("ApiError.isUnavailable", () => {
  it("is true only for unreachable and gateway statuses", () => {
    const flags = [0, 400, 404, 500, 502, 503, 504].map((s) => new ApiError(s, {}).isUnavailable);
    expect(flags).toEqual([true, false, false, false, true, true, true]);
  });
});

describe("unwrap", () => {
  it("turns an HTML error page into a friendly waking message", async () => {
    const result = Promise.resolve({ error: HTML_PAGE, response: new Response(HTML_PAGE, { status: 502 }) });
    const error = await unwrap(result).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 502, isUnavailable: true });
    expect((error as ApiError).message).not.toContain("<");
  });

  it("reports a network failure as unreachable", async () => {
    const error = await unwrap(Promise.reject(new TypeError("Failed to fetch"))).catch((e: unknown) => e);
    expect(error).toMatchObject({ status: 0, problem: UNREACHABLE_PROBLEM });
  });
});

describe("getJSON", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("parses JSON problems and hides HTML pages", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: "Bad layer" }), { status: 400 }))
      .mockResolvedValueOnce(new Response(HTML_PAGE, { status: 503 }));
    vi.stubGlobal("fetch", fetchMock);
    await expect(getJSON("/api/v1/layers/x")).rejects.toMatchObject({ status: 400, message: "Bad layer" });
    await expect(getJSON("/api/v1/layers/x")).rejects.toMatchObject({ status: 503, problem: WAKING_PROBLEM });
  });

  it("treats a 200 that is not JSON as unreachable", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(HTML_PAGE, { status: 200 })));
    await expect(getJSON("/api/v1/layers/x")).rejects.toMatchObject({ status: 0, problem: UNREACHABLE_PROBLEM });
  });
});
