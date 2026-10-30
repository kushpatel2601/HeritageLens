/**
 * Turns indexed chunks back into a readable document. The backend chunker prefixes every chunk
 * after the first on a page with a short tail of the previous one (retrieval context); a reader
 * must drop that carried text, and shift entity offsets (which are chunk-relative) accordingly.
 */
import type { Chunk, Entity } from "./api/types";

export interface Passage {
  chunk: Chunk;
  /** The chunk's own text, without the context carried over from the previous chunk. */
  body: string;
  /** Number of leading characters of `chunk.text` that `body` skips. */
  offset: number;
}

export interface EntitySpan {
  start: number;
  end: number;
  entity: Entity;
}

export type Piece = { text: string; entity: Entity | null };

const MIN_OVERLAP = 12;
const MAX_OVERLAP = 240;

/** Length of the carried-over prefix of `current` (a suffix of `previous`), or 0 if none. */
export function carriedLength(previous: string, current: string): number {
  const max = Math.min(MAX_OVERLAP, previous.length, current.length - 1);
  for (let k = max; k >= MIN_OVERLAP; k--) {
    if (/\s/.test(current[k]) && previous.endsWith(current.slice(0, k))) return k;
  }
  return 0;
}

/** Groups chunks by page (in reading order) and strips overlap between consecutive chunks. */
export function toPassages(chunks: readonly Chunk[]): Map<number, Passage[]> {
  const sorted = [...chunks].sort((a, b) => a.page_no - b.page_no || a.seq - b.seq);
  const pages = new Map<number, Passage[]>();
  for (const chunk of sorted) {
    const list = pages.get(chunk.page_no) ?? [];
    const previous = list[list.length - 1];
    let offset = previous ? carriedLength(previous.chunk.text, chunk.text) : 0;
    let body = chunk.text.slice(offset);
    const trimmed = body.trimStart();
    offset += body.length - trimmed.length;
    body = trimmed;
    list.push({ chunk, body, offset });
    pages.set(chunk.page_no, list);
  }
  return pages;
}

/**
 * Maps a chunk's entities onto its passage body. Offsets are trusted only when the text at the
 * shifted position still equals the entity's surface form; otherwise the first occurrence of the
 * surface is used, and entities that fall entirely in the dropped prefix are skipped.
 */
export function entitySpans(passage: Passage, entities: readonly Entity[]): EntitySpan[] {
  const spans: EntitySpan[] = [];
  for (const entity of entities) {
    if (entity.chunk_id !== passage.chunk.id || !entity.surface) continue;
    let start = entity.start - passage.offset;
    if (start < 0 || passage.body.slice(start, start + entity.surface.length) !== entity.surface) {
      if (entity.end <= passage.offset) continue;
      start = passage.body.indexOf(entity.surface);
      if (start < 0) continue;
    }
    spans.push({ start, end: start + entity.surface.length, entity });
  }
  return spans.sort((a, b) => a.start - b.start || b.end - a.end);
}

/** Splits text into plain and entity pieces; overlapping spans keep the earliest, longest one. */
export function splitEntities(text: string, spans: readonly EntitySpan[]): Piece[] {
  const out: Piece[] = [];
  let cursor = 0;
  for (const span of spans) {
    if (span.start < cursor || span.end > text.length) continue;
    if (span.start > cursor) out.push({ text: text.slice(cursor, span.start), entity: null });
    out.push({ text: text.slice(span.start, span.end), entity: span.entity });
    cursor = span.end;
  }
  if (cursor < text.length || out.length === 0) out.push({ text: text.slice(cursor), entity: null });
  return out;
}
