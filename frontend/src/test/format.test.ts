import { describe, expect, it } from "vitest";

import {
  formatBytes,
  formatDate,
  formatDuration,
  formatEra,
  formatRelative,
  formatYear,
  jobLabel,
  languageName,
  langAttr,
  latestRuns,
  scriptLang,
  splitHighlights,
  titleCase,
} from "@/lib/format";

describe("splitHighlights", () => {
  it("marks each [start, end) span", () => {
    expect(splitHighlights("Rani ki Vav, Patan", [[8, 11]])).toEqual([
      { text: "Rani ki ", mark: false },
      { text: "Vav", mark: true },
      { text: ", Patan", mark: false },
    ]);
  });

  it("merges overlapping and adjacent spans regardless of order", () => {
    expect(splitHighlights("abcdefgh", [[4, 6], [1, 3], [2, 4]])).toEqual([
      { text: "a", mark: false },
      { text: "bcdef", mark: true },
      { text: "gh", mark: false },
    ]);
  });

  it("clamps out-of-range spans and drops empty or malformed ones", () => {
    expect(splitHighlights("vav", [[-5, 1], [2, 99], [2, 2], [1], [Number.NaN, 2]])).toEqual([
      { text: "v", mark: true },
      { text: "a", mark: false },
      { text: "v", mark: true },
    ]);
  });

  it("handles Indic text using UTF-16 offsets", () => {
    const text = "રાણકી વાવ પાટણ";
    const start = text.indexOf("વાવ");
    const segments = splitHighlights(text, [[start, start + 3]]);
    expect(segments.filter((s) => s.mark).map((s) => s.text)).toEqual(["વાવ"]);
    expect(segments.map((s) => s.text).join("")).toBe(text);
  });

  it("returns a single plain segment when nothing is highlighted", () => {
    expect(splitHighlights("", [])).toEqual([{ text: "", mark: false }]);
    expect(splitHighlights("stepwell", [])).toEqual([{ text: "stepwell", mark: false }]);
  });
});

describe("eras and dates", () => {
  it("formats single years in CE and BCE", () => {
    expect(formatYear(1063)).toBe("1063 CE");
    expect(formatYear(-250)).toBe("250 BCE");
    expect(formatYear(null)).toBe("Undated");
  });

  it("collapses ranges that share an era", () => {
    expect(formatEra(1022, 1063)).toBe("1022–1063 CE");
    expect(formatEra(-300, -200)).toBe("300–200 BCE");
    expect(formatEra(-100, 200)).toBe("100 BCE – 200 CE");
    expect(formatEra(1499, 1499)).toBe("1499 CE");
    expect(formatEra(null, 1700)).toBe("1700 CE");
    expect(formatEra(undefined, null)).toBe("Undated");
  });

  it("renders calendar dates in UTC so they never shift a day", () => {
    expect(formatDate("2014-06-22")).toBe("22 Jun 2014");
    expect(formatDate("2026-01-31T23:30:00Z")).toBe("31 Jan 2026");
    expect(formatDate("not a date")).toBe("—");
    expect(formatDate(null)).toBe("—");
  });

  it("describes relative times, treating naive timestamps as UTC", () => {
    const now = Date.parse("2026-10-30T12:00:00Z");
    expect(formatRelative("2026-10-30T11:59:50Z", now)).toBe("just now");
    expect(formatRelative("2026-10-30T11:55:00", now)).toBe("5 minutes ago");
    expect(formatRelative("2026-10-30T09:00:00+00:00", now)).toBe("3 hours ago");
    expect(formatRelative("2026-10-28T12:00:00Z", now)).toBe("2 days ago");
    expect(formatRelative(undefined, now)).toBe("—");
  });

  it("formats durations at a sensible precision", () => {
    expect(formatDuration("2026-10-30T12:00:00Z", "2026-10-30T12:00:00.250Z")).toBe("250 ms");
    expect(formatDuration("2026-10-30T12:00:00Z", "2026-10-30T12:00:04.200Z")).toBe("4.2 s");
    expect(formatDuration("2026-10-30T12:00:00Z", "2026-10-30T12:02:05Z")).toBe("2 m 5 s");
    expect(formatDuration("2026-10-30T12:00:05Z", "2026-10-30T12:00:00Z")).toBe("—");
    expect(formatDuration(null, "2026-10-30T12:00:00Z")).toBe("—");
  });
});

describe("languages and scripts", () => {
  it("detects the script of free text", () => {
    expect(scriptLang("રાણકી વાવ")).toBe("gu");
    expect(scriptLang("रानी की वाव")).toBe("hi");
    expect(scriptLang("اردو")).toBe("ur");
    expect(scriptLang("Rani ki Vav")).toBeUndefined();
    expect(scriptLang("")).toBeUndefined();
  });

  it("names languages and only emits valid lang attributes", () => {
    expect(languageName("gu")).toBe("Gujarati");
    expect(languageName("xx")).toBe("XX");
    expect(languageName(null)).toBe("Unknown");
    expect(langAttr("hi")).toBe("hi");
    expect(langAttr("und-Latn")).toBeUndefined();
  });
});

describe("labels", () => {
  it("formats sizes and titles", () => {
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(1536)).toBe("1.5 KB");
    expect(formatBytes(25 * 1024 * 1024)).toBe("25 MB");
    expect(titleCase("image_embed")).toBe("Image Embed");
  });

  it("falls back to a title-cased job type", () => {
    expect(jobLabel("translate")).toBe("Translate to English");
    expect(jobLabel("new-step")).toBe("New Step");
  });
});

describe("latestRuns", () => {
  it("keeps the newest run of each stage and counts re-runs", () => {
    const jobs = [
      { id: 3, type: "index", created_at: "2026-10-29T10:00:02Z" },
      { id: 1, type: "extract", created_at: "2026-10-29T10:00:00Z" },
      { id: 9, type: "index", created_at: "2026-10-30T09:00:00Z" },
      { id: 5, type: "index", created_at: "2026-10-30T08:00:00Z" },
    ];
    expect(latestRuns(jobs).map(({ job, runs }) => [job.id, runs])).toEqual([
      [1, 1],
      [9, 3],
    ]);
    expect(latestRuns([])).toEqual([]);
  });
});
