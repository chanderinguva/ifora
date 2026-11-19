"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Badge, PageHeader, fmt } from "@/components/bits";
import { http } from "@/lib/http";

type Row = { id: number; application_name: string; user_email: string | null; user_name: string | null; reason: string | null; created_at: string; stage: number; stages_total: number;
  duration_days: number | null; escalated: boolean; sod_conflict: boolean; sod_apps: string[]; can_decide: boolean };

/** Requests waiting for me, at the stage the application's approval policy says I decide. */
export default function Approvals() {
  const [rows, setRows] = useState<Row[] | null>(null);
  const [note, setNote] = useState<Record<number, string>>({});
  const [exc, setExc] = useState<Record<number, string>>({});
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const started = useRef(false);

  const load = useCallback(() => {
    http<{ items: Row[] }>("/me/approvals").then((r) => setRows(r.items)).catch((e) => setMsg({ ok: false, text: e.message }));
  }, []);
  useEffect(() => { if (started.current) return; started.current = true; load(); }, [load]);

  async function decide(r: Row, verb: "approve" | "deny") {
    setMsg(null);
    try {
      await http(`/me/approvals/${r.id}/${verb}`, { method: "POST", body: { note: note[r.id] || null, exception_reason: exc[r.id] || null } });
      setMsg({ ok: true, text: `${verb === "approve" ? "Approved" : "Denied"}: ${r.application_name} for ${r.user_email}` });
      load();
    } catch (e) { setMsg({ ok: false, text: e instanceof Error ? e.message : "That did not work" }); }
  }

  return (
    <div className="max-w-4xl">
      <PageHeader title="Approvals" />
      {msg && <Alert variant={msg.ok ? "default" : "destructive"} className="mb-4" role="status"><AlertDescription>{msg.text}</AlertDescription></Alert>}
      {rows && rows.length === 0 && <p className="text-sm text-muted-foreground" data-testid="no-approvals">Nothing is waiting for your decision.</p>}
      <ul className="space-y-3" data-testid="approvals">
        {rows?.map((r) => (
          <li key={r.id}><Card data-testid={`approval-${r.id}`}><CardContent className="space-y-3 pt-6 text-sm">
            <div className="flex flex-wrap items-center gap-2">
              <strong>{r.application_name}</strong> for {r.user_name} <span className="text-muted-foreground">({r.user_email})</span>
              <Badge tone="info">Stage {r.stage} of {r.stages_total}</Badge>
              {r.duration_days && <Badge tone="neutral">{r.duration_days} days</Badge>}
              {r.escalated && <Badge tone="bad">Overdue</Badge>}
            </div>
            <div className="text-muted-foreground">Asked {fmt(r.created_at)}{r.reason ? ` — “${r.reason}”` : ""}</div>
            {r.sod_conflict && <Alert variant="destructive"><AlertDescription>Conflicts with access this person already has{r.sod_apps.length ? `: ${r.sod_apps.join(", ")}` : ""}. Approving needs an exception reason.</AlertDescription></Alert>}
            {r.can_decide ? (
              <div className="flex flex-wrap items-center gap-2">
                <Input aria-label={`Note for ${r.user_email}`} placeholder="Note (optional)" className="h-8 w-44" maxLength={500} value={note[r.id] ?? ""} onChange={(e) => setNote((n) => ({ ...n, [r.id]: e.target.value }))} />
                {r.sod_conflict && <Input aria-label={`Exception reason for ${r.user_email}`} placeholder="Exception reason" className="h-8 w-56" maxLength={500} value={exc[r.id] ?? ""} onChange={(e) => setExc((n) => ({ ...n, [r.id]: e.target.value }))} />}
                <Button size="sm" aria-label={`Approve ${r.application_name} for ${r.user_email}`} onClick={() => decide(r, "approve")}>Approve</Button>
                <Button size="sm" variant="outline" aria-label={`Deny ${r.application_name} for ${r.user_email}`} onClick={() => decide(r, "deny")}>Deny</Button>
              </div>
            ) : <p className="text-muted-foreground">You cannot decide this request (you are the requester or approved an earlier stage).</p>}
          </CardContent></Card></li>
        ))}
      </ul>
    </div>
  );
}
