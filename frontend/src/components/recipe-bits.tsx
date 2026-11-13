"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useContext, useEffect, useId, useRef, useState } from "react";
import { useDroppable } from "@dnd-kit/core";
import { FunctionsContext, PillFieldsContext, type FunctionInfo } from "@/components/recipe-editor/pill-context";
import { formulaPaths, openPill, parseSegments } from "@/lib/pills";
import { Badge, fieldClass, fmt } from "@/components/bits";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import { statusTone, type Job, type Pill } from "@/lib/recipes";

export function RecipeTabs() {
  const path = usePathname();
  const tabs = [
    { href: "/admin/recipes", label: "Recipes", active: path === "/admin/recipes" || /^\/admin\/recipes\/\d+/.test(path) },
    { href: "/admin/recipes/jobs", label: "Job history", active: path.startsWith("/admin/recipes/jobs") },
    { href: "/admin/recipes/health", label: "Health", active: path.startsWith("/admin/recipes/health") },
    { href: "/admin/recipes/connections", label: "Connections", active: path.startsWith("/admin/recipes/connections") },
    { href: "/admin/recipes/lookup-tables", label: "Lookup tables", active: path.startsWith("/admin/recipes/lookup-tables") },
  ];
  return (
    <nav aria-label="Automation" className="mb-4 flex gap-1 border-b">
      {tabs.map((t) => (
        <Link key={t.href} href={t.href} aria-current={t.active ? "page" : undefined}
          className={cn("-mb-px border-b-2 px-3 py-2 text-sm", t.active ? "border-primary font-medium" : "border-transparent text-muted-foreground hover:text-foreground")}>
          {t.label}
        </Link>
      ))}
    </nav>
  );
}

/**
 * A text field with a datapill picker. Choosing a pill inserts {{path}} at the cursor, so admins never have to
 * remember or type paths. `payload` adds a "payload field" entry for triggers that carry free-form JSON.
 */
export function PillInput({
  value, onChange, pills, label, required = false, multiline = false, payload = false, placeholder,
}: {
  value: string; onChange: (v: string) => void; pills: Pill[]; label: string; required?: boolean; multiline?: boolean; payload?: boolean; placeholder?: string;
}) {
  const ref = useRef<HTMLInputElement & HTMLTextAreaElement>(null);
  const reg = useContext(PillFieldsContext);
  const fid = useId();
  const [caret, setCaret] = useState(0);
  const [pick, setPick] = useState(0);
  const [dismissed, setDismissed] = useState(false);
  const { setNodeRef, isOver } = useDroppable({ id: `field:${fid}`, disabled: !reg });
  const insert = (path: string) => {
    const el = ref.current;
    const at = el?.selectionStart ?? value.length;
    const end = el?.selectionEnd ?? at;
    onChange(value.slice(0, at) + (path.startsWith("{{") ? path : `{{${path}}}`) + value.slice(end));
  };
  useEffect(() => {   // the tray inserts through this, so it always sees the current value
    if (!reg) return;
    reg.fields.set(fid, insert);
    return () => { reg.fields.delete(fid); };
  });
  const groups: [string, Pill[]][] = [
    ["Trigger", pills.filter((p) => p.path.startsWith("trigger."))],
    ["Earlier steps", pills.filter((p) => p.path.startsWith("steps."))],
  ];
  const fns = useContext(FunctionsContext);
  const pendingCaret = useRef<number | null>(null);
  useEffect(() => {   // put the cursor where a suggestion asked for it, once the new value is on screen
    if (pendingCaret.current !== null && ref.current) { ref.current.setSelectionRange(pendingCaret.current, pendingCaret.current); setCaret(pendingCaret.current); pendingCaret.current = null; }
  }, [value]);
  const open = dismissed ? null : openPill(value, caret);
  const formulaMode = !!open && open.query.startsWith("=");
  const token = open ? (open.query.match(/[A-Za-z0-9_.]*$/)?.[0] ?? "") : "";
  type Opt = { key: string; label: string; detail?: string; fn?: FunctionInfo; path?: string };
  const matches: Opt[] = !open ? [] : formulaMode
    ? [
        ...(token.includes(".") ? [] : fns.filter((f) => f.name.startsWith(token.toLowerCase())).slice(0, 6).map((f) => ({ key: "fn:" + f.name, label: f.signature, detail: f.description, fn: f }))),
        ...pills.filter((p) => token === "" || (p.label + " " + p.path).toLowerCase().includes(token.toLowerCase())).slice(0, 8).map((p) => ({ key: p.path, label: p.label, detail: p.path, path: p.path })),
      ].slice(0, 10)
    : pills.filter((p) => (p.label + " " + p.path).toLowerCase().includes(open.query.toLowerCase())).slice(0, 8).map((p) => ({ key: p.path, label: p.label, path: p.path }));
  const choose = (o: Opt) => {
    if (!open) return;
    if (formulaMode) {
      const insert = o.fn ? `${o.fn.name}()` : o.path!;
      const from = caret - token.length;
      const after = value.slice(caret);
      const close = after.includes("}}") ? "" : " }}";
      onChange(value.slice(0, from) + insert + close + after);
      pendingCaret.current = from + (o.fn ? o.fn.name.length + 1 : insert.length);
    } else {
      onChange(value.slice(0, open.start) + `{{${o.path}}}` + value.slice(caret));
    }
    setDismissed(false);
  };
  const known = (path: string) => pills.some((p) => p.path === path) || (payload && path.startsWith("trigger.payload."));
  const segments = parseSegments(value);
  const track = (e: { currentTarget: { selectionStart: number | null } }) => setCaret(e.currentTarget.selectionStart ?? 0);
  const keys = (e: React.KeyboardEvent) => {
    if (!open || matches.length === 0) return;
    if (e.key === "ArrowDown") { e.preventDefault(); setPick((pick + 1) % matches.length); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setPick((pick + matches.length - 1) % matches.length); }
    else if (e.key === "Enter" || e.key === "Tab") { e.preventDefault(); choose(matches[Math.min(pick, matches.length - 1)]); }
    else if (e.key === "Escape") { e.preventDefault(); setDismissed(true); }
  };
  const change = (v: string, c: number | null) => { onChange(v); setCaret(c ?? v.length); setPick(0); setDismissed(false); };
  const field = {
    "aria-label": label, "aria-required": required, required, placeholder, value, onKeyDown: keys, onKeyUp: track, onClick: track,
    onFocus: () => { if (reg) reg.active.current = fid; },
  };
  return (
    <div className="relative min-w-0" ref={setNodeRef}>
      <div className={cn("flex gap-2 rounded-md", isOver && "ring-2 ring-primary")}>
        {multiline ? (
          <textarea ref={ref} rows={3} {...field} onChange={(e) => change(e.target.value, e.target.selectionStart)} className={cn(fieldClass, "h-auto min-w-0 flex-1 font-mono")} />
        ) : (
          <Input ref={ref} {...field} onChange={(e) => change(e.target.value, e.target.selectionStart)} className="h-10 min-w-0 flex-1" />
        )}
        <select aria-label={`Insert datapill into ${label}`} className={cn(fieldClass, "!w-32 shrink-0")} value=""
          onChange={(e) => {
            const v = e.target.value;
            if (v === "__payload") {
              const name = window.prompt("Payload field name (letters, digits, _ or -; use . for nesting)");
              if (name && /^[A-Za-z0-9_-]+(\.[A-Za-z0-9_-]+)*$/.test(name)) insert(`trigger.payload.${name}`);
            } else if (v) insert(v);
          }}>
          <option value="">+ Datapill…</option>
          {groups.map(([g, list]) => list.length > 0 && (
            <optgroup key={g} label={g}>{list.map((p) => <option key={p.path} value={p.path}>{p.label}</option>)}</optgroup>
          ))}
          {payload && <option value="__payload">Payload field…</option>}
        </select>
      </div>
      {open && matches.length > 0 && (
        <ul role="listbox" aria-label={`Datapills for ${label}`} data-testid="pill-suggest" className="absolute z-20 mt-1 max-h-64 w-96 overflow-auto rounded-md border bg-popover p-1 text-sm shadow-md">
          {matches.map((o, i) => (
            <li key={o.key} role="option" aria-selected={i === pick}>
              <button type="button" tabIndex={-1} onMouseDown={(e) => { e.preventDefault(); choose(o); }}
                className={cn("block w-full rounded px-2 py-1 text-left", i === pick && "bg-muted")}>
                <span className={cn(o.fn && "font-mono")}>{o.fn ? "ƒ " : ""}{o.label}</span>
                {o.detail && <span className="block text-xs text-muted-foreground">{o.detail}</span>}
              </button>
            </li>
          ))}
        </ul>
      )}
      {segments.some((x) => !("text" in x)) && (
        <div className="mt-1 flex flex-wrap items-center gap-1 text-xs text-muted-foreground" data-testid="pill-preview" aria-hidden="true">
          {segments.map((x, i) => {
            if ("text" in x) return <span key={i} className="whitespace-pre-wrap">{x.text}</span>;
            if ("formula" in x) {
              const bad = formulaPaths(x.formula).find((p) => !known(p));
              return <span key={i} data-testid="formula-chip" title={bad ? `Not available at this step: ${bad}` : x.formula}
                className={cn("max-w-full truncate rounded-full px-2 py-0.5 font-mono", bad ? "bg-destructive/10 text-destructive" : "bg-selected text-selected-foreground")}>ƒ {x.formula}</span>;
            }
            return <span key={i} title={known(x.pill) ? x.pill : "Not available at this step"} className={cn("rounded-full px-2 py-0.5", known(x.pill) ? "bg-primary/10 text-foreground" : "bg-destructive/10 text-destructive")}>
              {pills.find((p) => p.path === x.pill)?.label ?? x.pill}</span>;
          })}
        </div>
      )}
    </div>
  );
}

const json = (v: unknown) => (v === null || v === undefined ? "" : JSON.stringify(v, null, 2));

export function JobView({ job }: { job: Job }) {
  return (
    <div className="space-y-3 text-sm" data-testid="job-view">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={statusTone(job.status)}>{job.status}</Badge>
        <span className="text-muted-foreground">
          {job.mode === "dry_run" ? "Draft validation (no changes sent)" : `Published version ${job.version ?? "?"}`} · {job.trigger_type} · started {fmt(job.created_at)}
        </span>
      </div>
      {job.status === "waiting" && job.approval && (
        <p className="rounded-md border p-2" data-testid="approval-note">Waiting for approval: {job.approval.message || "(no message)"}{job.approval.expires_at ? ` (gives up ${fmt(job.approval.expires_at)})` : ""}</p>
      )}
      {job.error && <p className="rounded-md border border-destructive/50 p-2 text-destructive" role="alert">{job.error}</p>}
      <ol className="space-y-2">
        {(job.steps ?? []).map((s) => (
          <li key={`${s.seq}-${s.attempt}-${s.status}`} className="rounded-md border p-3" data-testid="job-step">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-medium">{s.seq}. {s.name || s.type.replace(/_/g, " ")}</span>
              <code className="text-xs text-muted-foreground">{s.step_id}</code>
              <Badge tone={statusTone(s.status)}>{s.status}{s.attempt > 1 || s.status === "retrying" ? ` (attempt ${s.attempt})` : ""}</Badge>
            </div>
            {s.error && <p className="mt-1 text-destructive">{s.error}</p>}
            <div className="mt-2 grid gap-2 md:grid-cols-2">
              <div><div className="text-xs text-muted-foreground">Input (redacted)</div><pre className="max-h-48 overflow-auto rounded bg-muted p-2 text-xs">{json(s.input)}</pre></div>
              <div><div className="text-xs text-muted-foreground">Output (redacted)</div><pre className="max-h-48 overflow-auto rounded bg-muted p-2 text-xs">{json(s.output)}</pre></div>
            </div>
          </li>
        ))}
        {(job.steps ?? []).length === 0 && <li className="text-muted-foreground">No steps have run yet.</li>}
      </ol>
      <details>
        <summary className="cursor-pointer text-muted-foreground">Trigger data (redacted)</summary>
        <pre className="mt-1 max-h-60 overflow-auto rounded bg-muted p-2 text-xs">{json(job.trigger)}</pre>
      </details>
    </div>
  );
}
