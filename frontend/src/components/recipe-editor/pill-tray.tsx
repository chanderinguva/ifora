"use client";

import { useContext, useMemo, useState } from "react";
import { useDraggable } from "@dnd-kit/core";
import { FunctionsContext, PillFieldsContext } from "@/components/recipe-editor/pill-context";
import type { Pill } from "@/lib/recipes";

function group(p: Pill): string {
  if (p.path.startsWith("trigger.")) return "From the trigger";
  if (p.path.startsWith("loop.")) return "Current repeat item";
  if (p.path.startsWith("error.")) return "The error";
  const i = p.label.indexOf(": ");
  return i > 0 ? p.label.slice(0, i) : "Earlier steps";
}
const short = (p: Pill) => { const i = p.label.indexOf(": "); return p.path.startsWith("steps.") && i > 0 ? p.label.slice(i + 2) : p.label; };

function Chip({ pill, onClick }: { pill: Pill; onClick: () => void }) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({ id: `pill:${pill.path}` });
  return (
    <button type="button" ref={setNodeRef} {...attributes} {...listeners} onClick={onClick} data-testid="pill-chip" data-path={pill.path} title={pill.path}
      className={"cursor-grab touch-none rounded-full border bg-primary/10 px-2 py-0.5 text-xs hover:bg-primary/20 " + (isDragging ? "opacity-40" : "")}>
      {short(pill)}
    </button>
  );
}

/** Everything a step can read, grouped by where it comes from. Drag a chip onto a field, or click it to insert into the field you used last. */
export function PillTray({ pills }: { pills: Pill[] }) {
  const reg = useContext(PillFieldsContext);
  const [q, setQ] = useState("");
  const [note, setNote] = useState<string | null>(null);
  const groups = useMemo(() => {
    const m = new Map<string, Pill[]>();
    for (const p of pills) if ((p.label + p.path).toLowerCase().includes(q.toLowerCase())) m.set(group(p), [...(m.get(group(p)) ?? []), p]);
    return [...m.entries()];
  }, [pills, q]);
  const click = (p: Pill) => {
    const id = reg?.active.current;
    const put = id ? reg?.fields.get(id) : undefined;
    if (put) { put(p.path); setNote(null); } else setNote("Click into a field first, or drag the data onto one.");
  };
  const fns = useContext(FunctionsContext);
  const [fq, setFq] = useState("");
  const shownFns = fns.filter((f) => (f.name + " " + f.description).toLowerCase().includes(fq.toLowerCase()));
  const insertFn = (name: string) => {
    const id = reg?.active.current;
    const put = id ? reg?.fields.get(id) : undefined;
    if (put) { put(`{{= ${name}() }}`); setNote(null); } else setNote("Click into a field first.");
  };
  if (pills.length === 0 && fns.length === 0) return null;
  return (
    <div className="space-y-2 border-t pt-3" data-testid="pill-tray">
      <div className="text-sm font-medium">Data you can use here</div>
      <input aria-label="Search data" placeholder="Search…" value={q} onChange={(e) => setQ(e.target.value)} className="h-8 w-full rounded border bg-background px-2 text-sm" />
      {note && <p className="text-xs text-muted-foreground" role="note">{note}</p>}
      <div className="max-h-64 space-y-2 overflow-auto">
        {groups.map(([g, list]) => (
          <div key={g}>
            <div className="mb-1 text-xs font-medium uppercase text-muted-foreground">{g}</div>
            <div className="flex flex-wrap gap-1">{list.map((p) => <Chip key={p.path} pill={p} onClick={() => click(p)} />)}</div>
          </div>
        ))}
        {groups.length === 0 && <p className="text-xs text-muted-foreground">Nothing matches.</p>}
      </div>
      {fns.length > 0 && (
        <details className="text-sm" data-testid="formula-functions">
          <summary className="cursor-pointer font-medium">Formula functions ({fns.length})</summary>
          <p className="mt-1 text-xs text-muted-foreground">Type <code>{"{{="}</code> in a field to write a formula, e.g. <code>{"{{= upper(trigger.user.username) }}"}</code>. Click a function to insert it.</p>
          <input aria-label="Search functions" placeholder="Search functions…" value={fq} onChange={(e) => setFq(e.target.value)} className="my-2 h-8 w-full rounded border bg-background px-2 text-sm" />
          <ul className="max-h-60 space-y-1 overflow-auto">
            {shownFns.map((f) => (
              <li key={f.name}>
                <button type="button" onClick={() => insertFn(f.name)} className="block w-full rounded px-2 py-1 text-left hover:bg-muted" title={f.example}>
                  <span className="font-mono text-xs">{f.signature}</span>
                  <span className="block text-xs text-muted-foreground">{f.description}</span>
                </button>
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}
