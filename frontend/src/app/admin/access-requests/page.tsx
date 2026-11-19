"use client";

import { useCallback, useEffect, useState } from "react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Badge, PageHeader, fmt, td, th } from "@/components/bits";
import { http } from "@/lib/http";

type Row = { id: number; application_name: string; user_email: string | null; user_name: string | null; reason: string | null; status: string; decision_note: string | null;
  created_at: string; decided_at: string | null; decided_by_email: string | null;
  stage: number; stages_total: number; routed: boolean; sod_conflict: boolean; sod_apps: string[]; duration_days: number | null; exception_reason: string | null };
type Sod = { id: number; app_a_name: string | null; app_b_name: string | null; note: string | null };
type AppOpt = { id: number; name: string };
const TABS = ["pending", "approved", "denied", "canceled", "expired", "all"] as const;
const TONE: Record<string, "neutral" | "good" | "bad" | "info"> = { pending: "info", approved: "good", denied: "bad", canceled: "neutral", expired: "neutral" };

export default function AccessRequests() {
  const [status, setStatus] = useState<(typeof TABS)[number]>("pending");
  const [rows, setRows] = useState<Row[] | null>(null);
  const [note, setNote] = useState<Record<number, string>>({});
  const [exc, setExc] = useState<Record<number, string>>({});
  const [sod, setSod] = useState<Sod[]>([]);
  const [apps, setApps] = useState<AppOpt[]>([]);
  const [pair, setPair] = useState<{ a: string; b: string }>({ a: "", b: "" });
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const load = useCallback(() => {
    http<{ items: Row[] }>(`/admin/access-requests?status=${status}`).then((r) => setRows(r.items)).catch((e) => setMsg({ ok: false, text: e.message }));
  }, [status]);
  useEffect(() => { setRows(null); load(); }, [load]);
  const loadSod = useCallback(() => { http<{ items: Sod[] }>("/admin/access-requests/sod-rules").then((r) => setSod(r.items)).catch(() => {}); }, []);
  useEffect(() => {
    loadSod();
    http<{ Resources?: AppOpt[]; items?: AppOpt[] }>("/admin/applications?count=100").then((r) => setApps(r.items ?? r.Resources ?? [])).catch(() => {});
  }, [loadSod]);
  async function addRule() {
    setMsg(null);
    try { await http("/admin/access-requests/sod-rules", { method: "POST", body: { app_a_id: Number(pair.a), app_b_id: Number(pair.b) } }); setPair({ a: "", b: "" }); loadSod(); }
    catch (e) { setMsg({ ok: false, text: e instanceof Error ? e.message : "Could not add the rule" }); }
  }
  async function dropRule(id: number) { try { await http(`/admin/access-requests/sod-rules/${id}`, { method: "DELETE" }); loadSod(); } catch { /* shown on reload */ } }

  async function decide(r: Row, verb: "approve" | "deny") {
    setMsg(null);
    try {
      await http(`/admin/access-requests/${r.id}/${verb}`, { method: "POST", body: { note: note[r.id] || null, exception_reason: exc[r.id] || null } });
      setMsg({ ok: true, text: `${verb === "approve" ? "Approved" : "Denied"}: ${r.application_name} for ${r.user_email}` });
      load();
    } catch (e) { setMsg({ ok: false, text: e instanceof Error ? e.message : "That did not work" }); }
  }

  return (
    <div>
      <PageHeader title="Access requests" />
      <div role="tablist" aria-label="Request status" className="mb-4 flex gap-1 border-b">
        {TABS.map((t) => (
          <button key={t} role="tab" aria-selected={status === t} data-testid={`req-tab-${t}`} onClick={() => setStatus(t)}
            className={"px-3 py-2 text-sm capitalize " + (status === t ? "border-b-2 border-primary font-medium" : "text-muted-foreground")}>{t}</button>
        ))}
      </div>
      {msg && <Alert variant={msg.ok ? "default" : "destructive"} className="mb-4" role="status"><AlertDescription>{msg.text}</AlertDescription></Alert>}
      <Card>
        <CardContent className="overflow-x-auto p-0">
          <table className="w-full" data-testid="requests-table">
            <thead className="border-b"><tr><th className={th}>Person</th><th className={th}>Application</th><th className={th}>Reason</th><th className={th}>Requested</th><th className={th}>{status === "pending" ? "Decision" : "Status"}</th></tr></thead>
            <tbody>
              {rows?.map((r) => (
                <tr key={r.id} className="border-b align-top last:border-0" data-testid={`req-${r.id}`}>
                  <td className={td}>{r.user_name}<div className="text-xs text-muted-foreground">{r.user_email}</div>{r.sod_conflict && r.status === "pending" && <div className="text-xs text-destructive">Conflicts with {r.sod_apps.join(", ") || "existing access"}</div>}</td>
                  <td className={td}>{r.application_name}{r.routed && <div className="text-xs text-muted-foreground">Decided by approvers (stage {r.stage} of {r.stages_total})</div>}{r.duration_days && <div className="text-xs text-muted-foreground">{r.duration_days} days</div>}</td>
                  <td className={td + " max-w-xs break-words"}>{r.reason ?? "—"}</td>
                  <td className={td}>{fmt(r.created_at)}</td>
                  <td className={td}>
                    {r.status === "pending" && r.routed ? (
                      <Badge tone="info">With approvers</Badge>
                    ) : r.status === "pending" ? (
                      <div className="flex flex-wrap items-center gap-2">
                        <Input aria-label={`Note for ${r.user_email}`} placeholder="Note (optional)" className="h-8 w-40" maxLength={500} value={note[r.id] ?? ""} onChange={(e) => setNote((n) => ({ ...n, [r.id]: e.target.value }))} />
                        {r.sod_conflict && <Input aria-label={`Exception reason for ${r.user_email}`} placeholder="Exception reason" className="h-8 w-48" maxLength={500} value={exc[r.id] ?? ""} onChange={(e) => setExc((n) => ({ ...n, [r.id]: e.target.value }))} />}
                        <Button size="sm" aria-label={`Approve ${r.application_name} for ${r.user_email}`} onClick={() => decide(r, "approve")}>Approve</Button>
                        <Button size="sm" variant="outline" aria-label={`Deny ${r.application_name} for ${r.user_email}`} onClick={() => decide(r, "deny")}>Deny</Button>
                      </div>
                    ) : (
                      <div><Badge tone={TONE[r.status] ?? "neutral"}>{r.status}</Badge>{r.decided_by_email && <div className="text-xs text-muted-foreground">by {r.decided_by_email}</div>}{r.decision_note && <div className="text-xs">“{r.decision_note}”</div>}</div>
                    )}
                  </td>
                </tr>
              ))}
              {rows && rows.length === 0 && <tr><td className={td} colSpan={5}>No {status === "all" ? "" : status} requests.</td></tr>}
            </tbody>
          </table>
        </CardContent>
      </Card>
      <Card className="mt-8" data-testid="sod-card">
        <CardContent className="space-y-3 pt-6 text-sm">
          <h2 className="text-base font-semibold">Separation of duties</h2>
          <p className="text-muted-foreground">Pairs of applications nobody should hold at once. A request that would create the pair is flagged, and approving it needs an exception reason that is audited.</p>
          <ul className="divide-y" data-testid="sod-rules">
            {sod.map((x) => <li key={x.id} className="flex items-center justify-between py-2"><span>{x.app_a_name} ⇄ {x.app_b_name}</span><Button size="sm" variant="ghost" aria-label={`Remove rule ${x.app_a_name} and ${x.app_b_name}`} onClick={() => dropRule(x.id)}>Remove</Button></li>)}
            {sod.length === 0 && <li className="py-2 text-muted-foreground">No rules yet.</li>}
          </ul>
          <div className="flex flex-wrap items-center gap-2">
            {(["a", "b"] as const).map((k) => (
              <select key={k} aria-label={`Application ${k.toUpperCase()}`} className="h-9 rounded-md border bg-background px-2 text-sm" value={pair[k]} onChange={(e) => setPair((p) => ({ ...p, [k]: e.target.value }))}>
                <option value="">Application {k.toUpperCase()}…</option>
                {apps.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
              </select>
            ))}
            <Button size="sm" disabled={!pair.a || !pair.b || pair.a === pair.b} onClick={addRule} data-testid="add-sod-rule">Add rule</Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
