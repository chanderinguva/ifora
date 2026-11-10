"use client";

import { useEffect, useRef, useState } from "react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { PageHeader } from "@/components/bits";
import { http } from "@/lib/http";
import { useDirty } from "@/lib/use-dirty";
import { SaveButton } from "@/components/save-button";

type Policy = { min_length: number; require_mixed_case: boolean; require_digit: boolean; require_symbol: boolean; no_user_info: boolean; history_count: number;
  max_age_days: number; max_failed_attempts: number; lockout_minutes: number; session_lifetime_hours: number; idle_timeout_minutes: number };
type Resp = { policy: Policy; defaults: Policy; rules: string[]; users_past_max_age: number };

function Num({ id, label, hint, value, min, max, onChange }: { id: string; label: string; hint?: string; value: number; min: number; max: number; onChange: (n: number) => void }) {
  return (
    <div className="space-y-1">
      <Label htmlFor={id}>{label}</Label>
      <Input id={id} type="number" min={min} max={max} value={Number.isNaN(value) ? "" : value} onChange={(e) => onChange(e.target.value === "" ? NaN : Number(e.target.value))} data-testid={id} />
      {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
    </div>
  );
}
function Check({ id, label, hint, value, onChange }: { id: string; label: string; hint?: string; value: boolean; onChange: (b: boolean) => void }) {
  return (
    <label className="flex items-start gap-2 text-sm">
      <input id={id} type="checkbox" className="mt-1" checked={value} onChange={(e) => onChange(e.target.checked)} data-testid={id} />
      <span>{label}{hint && <span className="block text-xs text-muted-foreground">{hint}</span>}</span>
    </label>
  );
}

export default function SecurityPolicyPage() {
  const [data, setData] = useState<Resp | null>(null);
  const [p, setP] = useState<Policy | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const { dirty, markClean } = useDirty(p, p !== null);
  const started = useRef(false);
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    http<Resp>("/admin/security-policy").then((r) => { setData(r); setP(r.policy); markClean(); }).catch((e) => setMsg({ ok: false, text: e.message }));
  }, []);

  if (!p || !data) return msg ? <Alert variant="destructive"><AlertDescription>{msg.text}</AlertDescription></Alert> : <div className="text-sm text-muted-foreground">Loading…</div>;
  const set = (x: Partial<Policy>) => setP({ ...p, ...x });
  const invalid = Object.values(p).some((v) => typeof v === "number" && Number.isNaN(v));

  async function save() {
    setMsg(null);
    try {
      const r = await http<Resp>("/admin/security-policy", { method: "PUT", body: p });
      setData(r); setP(r.policy); markClean(); setMsg({ ok: true, text: "Policy saved. It applies from now on, including to sessions that are already open." });
    } catch (e) { setMsg({ ok: false, text: e instanceof Error ? e.message : "Could not save" }); }
  }

  return (
    <div className="max-w-3xl">
      <PageHeader title="Password and session policy" />
      {msg && <Alert variant={msg.ok ? "default" : "destructive"} className="mb-4" role="status"><AlertDescription>{msg.text}</AlertDescription></Alert>}
      {data.users_past_max_age > 0 && (
        <Alert className="mb-4" data-testid="age-warning"><AlertDescription>{data.users_past_max_age} active user{data.users_past_max_age > 1 ? "s have" : " has"} a password older than the saved maximum age and must choose a new one at their next sign-in.</AlertDescription></Alert>
      )}
      <form onSubmit={(e) => { e.preventDefault(); save(); }} className="space-y-6">
        <Card>
          <CardHeader><CardTitle>Password</CardTitle></CardHeader>
          <CardContent className="grid gap-4 sm:grid-cols-2">
            <Num id="sp-min" label="Minimum length" min={8} max={64} value={p.min_length} onChange={(n) => set({ min_length: n })} />
            <Num id="sp-history" label="Remember previous passwords" hint="0 turns reuse checking off" min={0} max={24} value={p.history_count} onChange={(n) => set({ history_count: n })} />
            <Num id="sp-age" label="Expire after (days)" hint="0 means passwords never expire" min={0} max={730} value={p.max_age_days} onChange={(n) => set({ max_age_days: n })} />
            <div className="space-y-3 sm:col-span-2">
              <Check id="sp-case" label="Require upper and lower case letters" value={p.require_mixed_case} onChange={(b) => set({ require_mixed_case: b })} />
              <Check id="sp-digit" label="Require a digit" value={p.require_digit} onChange={(b) => set({ require_digit: b })} />
              <Check id="sp-symbol" label="Require a symbol" value={p.require_symbol} onChange={(b) => set({ require_symbol: b })} />
              <Check id="sp-info" label="Must not contain the person’s name or the first part of their email" value={p.no_user_info} onChange={(b) => set({ no_user_info: b })} />
            </div>
            <p className="text-xs text-muted-foreground sm:col-span-2" data-testid="sp-rules">New passwords: {data.rules.join(" · ")}. Existing passwords are not rechecked; the rules apply when someone sets or changes a password.</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>Account lockout</CardTitle></CardHeader>
          <CardContent className="grid gap-4 sm:grid-cols-2">
            <Num id="sp-fails" label="Lock after this many failed sign-ins" min={3} max={20} value={p.max_failed_attempts} onChange={(n) => set({ max_failed_attempts: n })} />
            <Num id="sp-lock" label="Locked for (minutes)" min={1} max={1440} value={p.lockout_minutes} onChange={(n) => set({ lockout_minutes: n })} />
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>Sessions</CardTitle></CardHeader>
          <CardContent className="grid gap-4 sm:grid-cols-2">
            <Num id="sp-life" label="Maximum session length (hours)" min={1} max={168} value={p.session_lifetime_hours} onChange={(n) => set({ session_lifetime_hours: n })} />
            <Num id="sp-idle" label="Sign out after idle (minutes)" hint="Cannot be longer than the session length" min={5} max={1440} value={p.idle_timeout_minutes} onChange={(n) => set({ idle_timeout_minutes: n })} />
            <p className="text-xs text-muted-foreground sm:col-span-2">Shorter limits end sessions that are already open the next time they make a request.</p>
          </CardContent>
        </Card>
        <div className="flex gap-2">
          <SaveButton dirty={dirty} type="submit" disabled={invalid} data-testid="sp-save">Save policy</SaveButton>
          <Button type="button" variant="outline" onClick={() => setP(data.defaults)} data-testid="sp-defaults">Restore defaults</Button>
        </div>
      </form>
    </div>
  );
}
