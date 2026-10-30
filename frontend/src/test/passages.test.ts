import { describe, expect, it } from "vitest";

import type { Chunk, Entity } from "@/lib/api/types";
import { carriedLength, entitySpans, splitEntities, toPassages, type EntitySpan } from "@/lib/passages";

const FIRST = "On 14 January we reached Patan by the Saraswati river. The stepwell lay hidden below the fields.";
// The backend chunker prefixes each later chunk on a page with a tail of the previous one.
const TAIL = "The stepwell lay hidden below the fields.";
const NEW = "Rani ki Vav was built in 1063 CE by Queen Udayamati.";
const SECOND = `${TAIL} ${NEW}`;

function chunk(id: number, text: string, page_no = 1, seq = 0): Chunk {
  return { id, page_no, seq, char_start: 0, text, language: "en", script: "Latn", translation: null, translation_engine: null };
}

function entity(chunk_id: number, surface: string, start: number, kind = "place"): Entity {
  return {
    id: start + chunk_id * 1000,
    chunk_id,
    kind,
    surface,
    normalized: surface,
    site_id: null,
    lat: null,
    lon: null,
    year: null,
    start,
    end: start + surface.length,
  };
}

describe("carriedLength", () => {
  it("finds the tail carried over from the previous chunk", () => {
    expect(carriedLength(FIRST, SECOND)).toBe(TAIL.length);
  });

  it("returns 0 when chunks do not overlap", () => {
    expect(carriedLength(FIRST, NEW)).toBe(0);
  });

  it("ignores overlaps shorter than the minimum", () => {
    expect(carriedLength("hidden below the fields.", "fields. Next morning")).toBe(0);
  });

  it("only cuts at a word boundary", () => {
    expect(carriedLength("it lay hidden below the fields", "hidden below the fieldstone walls")).toBe(0);
  });

  it("works on Devanagari text", () => {
    const tail = "स्थानीय गाइड ने बताया कि यह वाव रानी उदयमती ने बनवाई थी।";
    expect(carriedLength(`सुबह सात बजे हम पाटण पहुँचे। ${tail}`, `${tail} परंपरा के अनुसार`)).toBe(tail.length);
  });
});

describe("toPassages", () => {
  it("groups by page in reading order and strips the carried prefix", () => {
    const pages = toPassages([chunk(3, "Page two text.", 2, 0), chunk(2, SECOND, 1, 1), chunk(1, FIRST, 1, 0)]);
    expect([...pages.keys()]).toEqual([1, 2]);
    const [a, b] = pages.get(1)!;
    expect(a).toMatchObject({ body: FIRST, offset: 0 });
    expect(b.body).toBe(NEW);
    expect(b.offset).toBe(TAIL.length + 1);
    expect(b.chunk.text.slice(b.offset)).toBe(b.body);
    expect(pages.get(2)![0]).toMatchObject({ body: "Page two text.", offset: 0 });
  });

  it("never strips across pages", () => {
    const pages = toPassages([chunk(1, FIRST, 1), chunk(2, SECOND, 2)]);
    expect(pages.get(2)![0]).toMatchObject({ body: SECOND, offset: 0 });
  });

  it("drops leading whitespace from a passage body", () => {
    const [p] = toPassages([chunk(1, "  \n Indented note")]).get(1)!;
    expect(p).toMatchObject({ body: "Indented note", offset: 4 });
  });
});

describe("entitySpans", () => {
  const passage = toPassages([chunk(1, FIRST), chunk(2, SECOND, 1, 1)]).get(1)![1];

  it("shifts chunk-relative offsets onto the passage body", () => {
    const date = entity(2, "1063 CE", SECOND.indexOf("1063 CE"), "date");
    const [span] = entitySpans(passage, [date]);
    expect(passage.body.slice(span.start, span.end)).toBe("1063 CE");
  });

  it("skips entities that lie entirely in the carried prefix", () => {
    expect(entitySpans(passage, [entity(2, "stepwell", SECOND.indexOf("stepwell"))])).toEqual([]);
  });

  it("falls back to the surface form when offsets are stale", () => {
    const [span] = entitySpans(passage, [entity(2, "Udayamati", 999)]);
    expect(passage.body.slice(span.start, span.end)).toBe("Udayamati");
  });

  it("ignores entities of other chunks and returns spans in order", () => {
    const spans = entitySpans(passage, [
      entity(2, "Udayamati", SECOND.indexOf("Udayamati")),
      entity(1, "Patan", FIRST.indexOf("Patan")),
      entity(2, "Rani ki Vav", SECOND.indexOf("Rani ki Vav"), "site"),
    ]);
    expect(spans.map((s) => s.entity.surface)).toEqual(["Rani ki Vav", "Udayamati"]);
  });
});

describe("splitEntities", () => {
  const vav = entity(1, "Rani ki Vav", 0, "site");
  const span = (start: number, end: number, e: Entity = vav): EntitySpan => ({ start, end, entity: e });

  it("splits text into plain and entity pieces that rejoin losslessly", () => {
    const pieces = splitEntities(NEW, [span(0, 11), span(25, 32)]);
    expect(pieces.map((p) => p.text).join("")).toBe(NEW);
    expect(pieces.filter((p) => p.entity).map((p) => p.text)).toEqual(["Rani ki Vav", "1063 CE"]);
  });

  it("keeps the earliest span when spans overlap, and drops out-of-range ones", () => {
    const pieces = splitEntities(NEW, [span(0, 11), span(5, 11), span(40, 500)]);
    expect(pieces.filter((p) => p.entity).map((p) => p.text)).toEqual(["Rani ki Vav"]);
    expect(pieces.map((p) => p.text).join("")).toBe(NEW);
  });

  it("returns one plain piece without spans", () => {
    expect(splitEntities("", [])).toEqual([{ text: "", entity: null }]);
  });
});
