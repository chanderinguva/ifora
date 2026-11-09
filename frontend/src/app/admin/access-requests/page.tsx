"use client";

import { useCallback, useEffect, useState } from "react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Badge, PageHeader, fmt, td, th } from "@/components/bits";
import { http } from "@/lib/http";

type Row = { id: number; application_name: string; user_email: string | null; user_name: string | null; reason: string | null; status: string; decision_note: string | null;
  created_at: string; decided_at: string | null; decided_by_email: string | null };
const TABS = ["pending", "approved", "denied", "canceled", "all"] as const;
const TONE: Record<string, "neutral" | "good" | "bad" | "info"> = { pending: "info", approved: "good", denied: "bad", canceled: "neutral" };

export default function AccessRequests() {
  const [status, setStatus] = useState<(typeof TABS)[number]>("pending");
  const [rows, setRows] = useState<Row[] | null>(null);
  const [note, setNote] = useState<Record<number, string>>({});
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const load = useCallback(() => {
    http<{ items: Row[] }>(`/admin/access-requests?status=${status}`).then((r) => setRows(r.items)).catch((e) => setMsg({ ok: false, text: e.message }));
  }, [status]);
  useEffect(() => { setRows(null); load(); }, [load]);

  async function decide(r: Row, verb: "approve" | "deny") {
    setMsg(null);
    try {
      await http(`/admin/access-requests/${r.id}/${verb}`, { method: "POST", body: { note: note[r.id] || null } });
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
                  <td className={td}>{r.user_name}<div className="text-xs text-muted-foreground">{r.user_email}</div></td>
                  <td className={td}>{r.application_name}</td>
                  <td className={td + " max-w-xs break-words"}>{r.reason ?? "—"}</td>
                  <td className={td}>{fmt(r.created_at)}</td>
                  <td className={td}>
                    {r.status === "pending" ? (
                      <div className="flex flex-wrap items-center gap-2">
                        <Input aria-label={`Note for ${r.user_email}`} placeholder="Note (optional)" className="h-8 w-40" maxLength={500} value={note[r.id] ?? ""} onChange={(e) => setNote((n) => ({ ...n, [r.id]: e.target.value }))} />
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
    </div>
  );
}
