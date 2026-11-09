/** Splitting a field value into text and {{datapill}} segments (the stored form is always plain {{path}} text). */
export type Segment = { text: string } | { pill: string } | { formula: string };

export function parseSegments(value: string): Segment[] {
  const out: Segment[] = [];
  let i = 0;
  let textStart = 0;
  const flush = (end: number) => { if (end > textStart) out.push({ text: value.slice(textStart, end) }); };
  while (i < value.length) {
    const j = value.indexOf("{{", i);
    if (j < 0) break;
    let k = j + 2;
    while (value[k] === " " || value[k] === "\t") k++;
    if (value[k] === "=") {                      // a formula: ends at the first }} outside quoted text
      let q: string | null = null;
      let e = k + 1;
      for (; e < value.length; e++) {
        const c = value[e];
        if (q) { if (c === "\\") e++; else if (c === q) q = null; }
        else if (c === "'" || c === '"') q = c;
        else if (value.startsWith("}}", e)) break;
      }
      if (e >= value.length) break;              // unfinished: shown as plain text
      flush(j);
      out.push({ formula: value.slice(k + 1, e).trim() });
      i = textStart = e + 2;
      continue;
    }
    const m = /^\{\{\s*([A-Za-z0-9_.-]+)\s*\}\}/.exec(value.slice(j));
    if (m) { flush(j); out.push({ pill: m[1] }); i = textStart = j + m[0].length; } else i = j + 2;
  }
  flush(value.length);
  return out;
}

/** Datapill paths a formula reads (anything that looks like root.name...), for flagging unknown ones. */
export function formulaPaths(expr: string): string[] {
  const noText = expr.replace(/'(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*"/g, '""');
  return [...noText.matchAll(/\b(?:trigger|steps|recipe|job|error|loop)(?:\.[A-Za-z0-9_]+)+/g)].map((m) => m[0]);
}

/** The unfinished `{{query` just before the caret, if any: where the suggestion list should open. */
export function openPill(value: string, caret: number): { start: number; query: string } | null {
  const before = value.slice(0, caret);
  const i = before.lastIndexOf("{{");
  if (i < 0 || before.slice(i).includes("}}")) return null;
  return { start: i, query: before.slice(i + 2).trim() };
}
