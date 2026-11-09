/** Splitting a field value into text and {{datapill}} segments (the stored form is always plain {{path}} text). */
export type Segment = { text: string } | { pill: string };

export function parseSegments(value: string): Segment[] {
  const out: Segment[] = [];
  let last = 0;
  for (const m of value.matchAll(/\{\{\s*([A-Za-z0-9_.-]+)\s*\}\}/g)) {
    if (m.index! > last) out.push({ text: value.slice(last, m.index) });
    out.push({ pill: m[1] });
    last = m.index! + m[0].length;
  }
  if (last < value.length) out.push({ text: value.slice(last) });
  return out;
}

/** The unfinished `{{query` just before the caret, if any: where the suggestion list should open. */
export function openPill(value: string, caret: number): { start: number; query: string } | null {
  const before = value.slice(0, caret);
  const i = before.lastIndexOf("{{");
  if (i < 0 || before.slice(i).includes("}}")) return null;
  return { start: i, query: before.slice(i + 2).trim() };
}
