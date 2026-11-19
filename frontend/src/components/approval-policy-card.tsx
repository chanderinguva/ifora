"use client";

import { useEffect, useRef, useState } from "react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { fieldClass } from "@/components/bits";
import { http } from "@/lib/http";

type Stage = { kind: "owner" | "manager" | "group"; group_id: number | null };
type Policy = { stages: (Stage & { position: number })[]; durations: number[]; timeout_hours: number | null };
type Group = { id: number; name: string };
const KINDS: { id: Stage["kind"]; label: string }[] = [{ id: "owner", label: "Application owner" }, { id: "manager", label: "Requester's manager" }, { id: "group", label: "Members of a group" }];

/** Who approves requests for this application (1-3 ordered stages), how long grants last, and when a waiting request is nudged. */
export function ApprovalPolicyCard({ appId }: { appId: number }) {
  const [stages, setStages] = useState<Stage[] | null>(null);
  const [durations, setDurations] = useState("");
  const [timeout, setTimeoutH] = useState("");
  const [groups, setGroups] = useState<Group[]>([]);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    http<Policy>(`/admin/applications/${appId}/approval-policy`).then((p) => {
      setStages(p.stages.map((s) => ({ kind: s.kind, group_id: s.group_id })));
      setDurations(p.durations.join(", "));
      setTimeoutH(p.timeout_hours ? String(p.timeout_hours) : "");
    }).catch((e) => setMsg({ ok: false, text: e.message }));
    http<{ Resources: Group[] }>("/admin/groups?count=100&sortBy=name").then((r) => setGroups(r.Resources)).catch(() => {});
  }, [appId]);

  const setStage = (i: number, s: Stage) => setStages((cur) => (cur ?? []).map((x, j) => (j === i ? s : x)));

  async function save() {
    setMsg(null);
    const days = durations.split(/[,\s]+/).filter(Boolean).map(Number);
    if (days.some((d) => !Number.isInteger(d) || d < 1)) { setMsg({ ok: false, text: "Durations are whole numbers of days, for example 7, 30." }); return; }
    try {
      const p = await http<Policy>(`/admin/applications/${appId}/approval-policy`, { method: "PUT", body: { stages, durations: days, timeout_hours: timeout ? Number(timeout) : null } });
      setStages(p.stages.map((s) => ({ kind: s.kind, group_id: s.group_id })));
      setMsg({ ok: true, text: "Saved" });
    } catch (e) { setMsg({ ok: false, text: e instanceof Error ? e.message : "Could not save" }); }
  }

  if (!stages) return msg ? <Alert variant="destructive" className="mb-6"><AlertDescription>{msg.text}</AlertDescription></Alert> : null;
  return (
    <Card className="mb-6" data-testid="approval-policy-card">
      <CardHeader><CardTitle>Approval policy</CardTitle></CardHeader>
      <CardContent className="space-y-4 text-sm">
        <p className="text-muted-foreground">With no stages, any administrator can decide a request. Add stages to route requests to the right people; access is granted only after the last stage approves, and nobody can approve their own request or two stages of one request.</p>
        <ol className="space-y-2" data-testid="approval-stages">
          {stages.map((s, i) => (
            <li key={i} className="flex flex-wrap items-center gap-2">
              <span className="w-16 text-muted-foreground">Stage {i + 1}</span>
              <select aria-label={`Stage ${i + 1} approver`} className={fieldClass + " w-56"} value={s.kind} onChange={(e) => setStage(i, { kind: e.target.value as Stage["kind"], group_id: null })}>
                {KINDS.map((k) => <option key={k.id} value={k.id}>{k.label}</option>)}
              </select>
              {s.kind === "group" && (
                <select aria-label={`Stage ${i + 1} group`} className={fieldClass + " w-56"} value={s.group_id ?? ""} onChange={(e) => setStage(i, { kind: "group", group_id: e.target.value ? Number(e.target.value) : null })}>
                  <option value="">Choose a group…</option>
                  {groups.map((g) => <option key={g.id} value={g.id}>{g.name}</option>)}
                </select>
              )}
              <Button size="sm" variant="ghost" aria-label={`Remove stage ${i + 1}`} onClick={() => setStages(stages.filter((_, j) => j !== i))}>Remove</Button>
            </li>
          ))}
        </ol>
        {stages.length < 3 && <Button size="sm" variant="outline" data-testid="add-stage" onClick={() => setStages([...stages, { kind: "owner", group_id: null }])}>Add stage</Button>}
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-1"><label htmlFor="ap-durations" className="font-medium">Allowed grant durations (days)</label>
            <Input id="ap-durations" placeholder="7, 30, 90 — empty means permanent access" value={durations} onChange={(e) => setDurations(e.target.value)} />
            <p className="text-xs text-muted-foreground">Requesters pick one. The assignment is removed automatically when it ends.</p></div>
          <div className="space-y-1"><label htmlFor="ap-timeout" className="font-medium">Remind approvers after (hours)</label>
            <Input id="ap-timeout" inputMode="numeric" placeholder="empty means never" value={timeout} onChange={(e) => setTimeoutH(e.target.value.replace(/\D/g, ""))} />
            <p className="text-xs text-muted-foreground">One reminder email; the request is then marked escalated.</p></div>
        </div>
        <div className="flex items-center gap-3"><Button size="sm" onClick={save} data-testid="approval-policy-save">Save policy</Button>
          {msg && <span role="status" className={msg.ok ? "text-muted-foreground" : "text-destructive"}>{msg.text}</span>}</div>
      </CardContent>
    </Card>
  );
}
