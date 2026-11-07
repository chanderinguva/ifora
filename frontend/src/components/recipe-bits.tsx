"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useRef } from "react";
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
  value, onChange, pills, label, multiline = false, payload = false, placeholder,
}: {
  value: string; onChange: (v: string) => void; pills: Pill[]; label: string; multiline?: boolean; payload?: boolean; placeholder?: string;
}) {
  const ref = useRef<HTMLInputElement & HTMLTextAreaElement>(null);
  const insert = (path: string) => {
    const el = ref.current;
    const at = el?.selectionStart ?? value.length;
    const end = el?.selectionEnd ?? at;
    onChange(value.slice(0, at) + `{{${path}}}` + value.slice(end));
  };
  const groups: [string, Pill[]][] = [
    ["Trigger", pills.filter((p) => p.path.startsWith("trigger."))],
    ["Earlier steps", pills.filter((p) => p.path.startsWith("steps."))],
  ];
  return (
    <div className="flex gap-2">
      {multiline ? (
        <textarea ref={ref} aria-label={label} placeholder={placeholder} rows={3} value={value} onChange={(e) => onChange(e.target.value)} className={cn(fieldClass, "h-auto font-mono")} />
      ) : (
        <Input ref={ref} aria-label={label} placeholder={placeholder} value={value} onChange={(e) => onChange(e.target.value)} className="h-10" />
      )}
      <select aria-label={`Insert datapill into ${label}`} className={cn(fieldClass, "!w-44 shrink-0")} value=""
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
  );
}

const json = (v: unknown) => (v === null || v === undefined ? "" : JSON.stringify(v, null, 2));

export function JobView({ job }: { job: Job }) {
  return (
    <div className="space-y-3 text-sm" data-testid="job-view">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={statusTone(job.status)}>{job.status}</Badge>
        <span className="text-muted-foreground">
          {job.mode === "dry_run" ? "Test run (nothing was changed)" : `Version ${job.version ?? "?"}`} · {job.trigger_type} · started {fmt(job.created_at)}
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
              <div><div className="text-xs uppercase text-muted-foreground">Input (redacted)</div><pre className="max-h-48 overflow-auto rounded bg-muted p-2 text-xs">{json(s.input)}</pre></div>
              <div><div className="text-xs uppercase text-muted-foreground">Output (redacted)</div><pre className="max-h-48 overflow-auto rounded bg-muted p-2 text-xs">{json(s.output)}</pre></div>
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
