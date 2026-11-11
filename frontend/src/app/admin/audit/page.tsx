"use client";

import { useCallback, useEffect, useState } from "react";
import { Download, Star, X } from "lucide-react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { PageHeader, Pager, fieldClass, fmt, td, th } from "@/components/bits";
import { API_URL } from "@/lib/api";
import { http, pageQs, qs, type Page } from "@/lib/http";
import type { AuditEvent } from "@/lib/types";

const PAGE_SIZE = 25;
const RANGES: [string, string, number | null][] = [["any", "Any time", null], ["1h", "Last hour", 3600e3], ["24h", "Last 24 hours", 864e5], ["7d", "Last 7 days", 6048e5], ["30d", "Last 30 days", 2592e6]];
type Filters = { q: string; action: string; range: string; target_type: string; target_id: string };
const EMPTY: Filters = { q: "", action: "", range: "any", target_type: "", target_id: "" };
const SAVED_KEY = "idf.audit.saved";

function params(f: Filters) {
  const ms = RANGES.find((r) => r[0] === f.range)?.[2];
  return { q: f.q, action: f.action, target_type: f.target_type, target_id: f.target_id, since: ms ? new Date(Date.now() - ms).toISOString() : "" };
}

function loadSaved(): Record<string, Filters> {
  try { return JSON.parse(localStorage.getItem(SAVED_KEY) || "{}"); } catch { return {}; }
}

export default function AuditPage() {
  const [data, setData] = useState<Page<AuditEvent> | null>(null);
  const [actions, setActions] = useState<string[]>([]);
  const [f, setF] = useState<Filters>(EMPTY);
  const [page, setPage] = useState(1);
  const [open, setOpen] = useState<AuditEvent | null>(null);
  const [saved, setSaved] = useState<Record<string, Filters>>({});
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  useEffect(() => {
    http<{ items: string[] }>("/admin/audit/actions").then((r) => setActions(r.items)).catch(() => {});
    setSaved(loadSaved());
    const sp = new URLSearchParams(window.location.search);
    setF((p) => ({ ...p, action: sp.get("action") ?? "", target_type: sp.get("target_type") ?? "", target_id: sp.get("target_id") ?? "" }));
  }, []);

  const load = useCallback(() => {
    setError(null);
    http<Page<AuditEvent>>(`/admin/audit${qs({ ...params(f), ...pageQs(page, PAGE_SIZE) })}`).then(setData).catch((e) => setError(e.message));
  }, [f, page]);
  useEffect(() => { const t = setTimeout(load, 250); return () => clearTimeout(t); }, [load]);

  const set = (p: Partial<Filters>) => { setF((x) => ({ ...x, ...p })); setPage(1); };

  async function exportCsv() {
    setNote(null);
    try {
      const res = await fetch(`${API_URL}/api/v1/admin/audit/export${qs(params(f))}`, { credentials: "include" });
      if (!res.ok) throw new Error(`Export failed (${res.status})`);
      const blob = await res.blob();
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = "audit-log.csv";
      a.click();
      URL.revokeObjectURL(a.href);
      if (res.headers.get("X-Truncated") === "true") setNote("The export holds the newest 10,000 matching events; narrow the filters to get the rest.");
    } catch (e) { setError(e instanceof Error ? e.message : "Export failed"); }
  }

  function saveFilter() {
    const name = window.prompt("Name this filter");
    if (!name?.trim()) return;
    const next = { ...loadSaved(), [name.trim().slice(0, 60)]: f };
    try { localStorage.setItem(SAVED_KEY, JSON.stringify(next)); } catch { /* storage may be unavailable */ }
    setSaved(next);
  }
  function dropFilter(name: string) {
    const next = { ...loadSaved() }; delete next[name];
    try { localStorage.setItem(SAVED_KEY, JSON.stringify(next)); } catch { /* ignore */ }
    setSaved(next);
  }

  const active = JSON.stringify(f) !== JSON.stringify(EMPTY);

  return (
    <div>
      <PageHeader title="System log">
        <Button variant="outline" size="sm" onClick={exportCsv} data-testid="audit-export"><Download className="mr-1 h-4 w-4" /> Export CSV</Button>
      </PageHeader>

      <div className="mb-3 flex flex-wrap items-end gap-2" data-testid="audit-filters">
        <Input aria-label="Search events" placeholder="Search action, actor, IP, details…" className="w-72" value={f.q} onChange={(e) => set({ q: e.target.value })} />
        <select aria-label="Filter by action" className={fieldClass + " w-56"} value={f.action} onChange={(e) => set({ action: e.target.value })}>
          <option value="">All actions</option>
          {actions.map((a) => <option key={a} value={a}>{a}</option>)}
        </select>
        <select aria-label="Time range" className={fieldClass + " w-44"} value={f.range} onChange={(e) => set({ range: e.target.value })}>
          {RANGES.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
        </select>
        {active && <Button variant="ghost" size="sm" onClick={() => { setF(EMPTY); setPage(1); }}>Clear</Button>}
        {active && <Button variant="outline" size="sm" onClick={saveFilter} data-testid="audit-save-filter"><Star className="mr-1 h-4 w-4" /> Save filter</Button>}
      </div>
      {(f.target_type || f.target_id) && (
        <p className="mb-3 text-sm text-muted-foreground">Showing events for {f.target_type || "target"} #{f.target_id}. <button className="underline" onClick={() => set({ target_type: "", target_id: "" })}>Remove</button></p>
      )}
      {Object.keys(saved).length > 0 && (
        <div className="mb-3 flex flex-wrap items-center gap-2 text-sm" data-testid="audit-saved">
          <span className="text-muted-foreground">Saved:</span>
          {Object.entries(saved).map(([name, sf]) => (
            <span key={name} className="inline-flex items-center rounded-full border">
              <button className="px-3 py-1 hover:bg-accent" onClick={() => { setF({ ...EMPTY, ...sf }); setPage(1); }}>{name}</button>
              <button aria-label={`Delete saved filter ${name}`} className="px-2 py-1 hover:bg-accent" onClick={() => dropFilter(name)}><X className="h-3 w-3" /></button>
            </span>
          ))}
          <span className="text-xs text-muted-foreground">(kept in this browser only)</span>
        </div>
      )}

      {error && <Alert variant="destructive" className="mb-4"><AlertDescription>{error}</AlertDescription></Alert>}
      {note && <Alert className="mb-4" role="status"><AlertDescription>{note}</AlertDescription></Alert>}
      <Card>
        <CardContent className="overflow-x-auto p-0">
          <table className="w-full" data-testid="audit-table">
            <thead className="border-b">
              <tr><th className={th}>When</th><th className={th}>Actor</th><th className={th}>Action</th><th className={th}>Target</th><th className={th}>IP</th></tr>
            </thead>
            <tbody>
              {data?.Resources.map((e) => (
                <tr key={e.id} className="cursor-pointer border-b align-top last:border-0 hover:bg-accent/30" onClick={() => setOpen(e)}>
                  <td className={td}>{fmt(e.timestamp)}</td>
                  <td className={td}>{e.actor_email ?? (e.actor_id ? `#${e.actor_id}` : "system")}</td>
                  <td className={td}><button className="font-medium underline-offset-4 hover:underline" data-testid={`audit-open-${e.id}`} onClick={(ev) => { ev.stopPropagation(); setOpen(e); }}>{e.action}</button></td>
                  <td className={td}>{e.target_type ? `${e.target_type} #${e.target_id ?? ""}` : "—"}</td>
                  <td className={td}>{e.actor_ip_address ?? "—"}</td>
                </tr>
              ))}
              {data && data.Resources.length === 0 && <tr><td className={td} colSpan={5}>No events match.</td></tr>}
            </tbody>
          </table>
        </CardContent>
      </Card>
      {data && <Pager page={page} pageSize={PAGE_SIZE} total={data.totalResults} onPage={setPage} />}

      {open && (
        <div className="fixed inset-0 z-40 flex justify-end bg-black/30" onClick={() => setOpen(null)}>
          <aside role="dialog" aria-modal="true" aria-label="Event details" data-testid="audit-drawer" className="h-full w-full max-w-md overflow-y-auto border-l bg-background p-6 shadow-xl"
            onClick={(e) => e.stopPropagation()} onKeyDown={(e) => { if (e.key === "Escape") setOpen(null); }}>
            <div className="mb-4 flex items-start justify-between gap-2">
              <h2 className="text-lg font-semibold">{open.action}</h2>
              <Button variant="ghost" size="sm" autoFocus aria-label="Close details" onClick={() => setOpen(null)}><X className="h-4 w-4" /></Button>
            </div>
            <dl className="space-y-3 text-sm">
              {([["When", fmt(open.timestamp)], ["Actor", open.actor_email ?? (open.actor_id ? `#${open.actor_id}` : "system")], ["IP address", open.actor_ip_address ?? "—"],
                ["Target", open.target_type ? `${open.target_type} #${open.target_id ?? ""}` : "—"], ["Event ID", String(open.id)]] as const).map(([k, v]) => (
                <div key={k}><dt className="text-xs text-muted-foreground">{k}</dt><dd className="break-words">{v}</dd></div>
              ))}
              <div><dt className="text-xs text-muted-foreground">Details</dt>
                <dd><pre className="mt-1 max-h-96 overflow-auto rounded-md bg-muted p-3 text-xs" data-testid="audit-drawer-json">{open.metadata ? JSON.stringify(open.metadata, null, 2) : "No additional details."}</pre></dd></div>
            </dl>
            {open.target_type && open.target_id && (
              <Button className="mt-4" variant="outline" size="sm" onClick={() => { set({ target_type: open.target_type!, target_id: open.target_id!, q: "", action: "" }); setOpen(null); }}>Show events for this target</Button>
            )}
          </aside>
        </div>
      )}
    </div>
  );
}
