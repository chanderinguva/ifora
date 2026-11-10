"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { fieldClass } from "@/components/bits";
import { http } from "@/lib/http";
import { useDirty } from "@/lib/use-dirty";
import { SaveButton } from "@/components/save-button";

type Zone = { id: number; name: string };
type Policy = { configured: boolean; require_mfa: boolean; reauth_minutes: number | null; allowed_zone_ids: number[]; blocked_zone_ids: number[] };
const REAUTH = [[0, "Not required"], [5, "5 minutes"], [15, "15 minutes"], [30, "30 minutes"], [60, "1 hour"], [240, "4 hours"], [480, "8 hours"], [1440, "24 hours"]] as const;

export function AuthPolicyCard({ appId }: { appId: number }) {
  const [p, setP] = useState<Policy | null>(null);
  const [zones, setZones] = useState<Zone[]>([]);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const { dirty, markClean } = useDirty(p && { require_mfa: p.require_mfa, reauth_minutes: p.reauth_minutes || null, allowed: [...p.allowed_zone_ids].sort(), blocked: [...p.blocked_zone_ids].sort() }, p !== null);
  const load = useCallback(() => {
    http<Policy>(`/admin/applications/${appId}/policy`).then((x) => { setP(x); markClean(); }).catch((e) => setMsg({ ok: false, text: e.message }));
    http<{ items: Zone[] }>("/admin/network-zones").then((r) => setZones(r.items)).catch(() => {});
  }, [appId, markClean]);
  useEffect(load, [load]);
  if (!p) return null;

  const toggle = (key: "allowed_zone_ids" | "blocked_zone_ids", other: "allowed_zone_ids" | "blocked_zone_ids", id: number) => {
    const has = p[key].includes(id);
    setP({ ...p, [key]: has ? p[key].filter((x) => x !== id) : [...p[key], id], [other]: p[other].filter((x) => x !== id) });
  };
  async function save() {
    setMsg(null);
    try {
      const r = await http<Policy>(`/admin/applications/${appId}/policy`, { method: "PUT", body: { require_mfa: p!.require_mfa, reauth_minutes: p!.reauth_minutes || null, allowed_zone_ids: p!.allowed_zone_ids, blocked_zone_ids: p!.blocked_zone_ids } });
      setP(r); markClean(); setMsg({ ok: true, text: "Policy saved" });
    } catch (e) { setMsg({ ok: false, text: e instanceof Error ? e.message : "Failed" }); }
  }
  async function remove() {
    try { await http(`/admin/applications/${appId}/policy`, { method: "DELETE" }); setMsg({ ok: true, text: "Policy removed" }); load(); }
    catch (e) { setMsg({ ok: false, text: e instanceof Error ? e.message : "Failed" }); }
  }

  const checks = (key: "allowed_zone_ids" | "blocked_zone_ids", other: "allowed_zone_ids" | "blocked_zone_ids", label: string, hint: string) => (
    <fieldset className="space-y-1">
      <legend className="text-sm font-medium">{label}</legend>
      <p className="text-xs text-muted-foreground">{hint}</p>
      {zones.length === 0 ? <p className="text-sm text-muted-foreground">No zones yet. <Link className="underline" href="/admin/network-zones">Create one</Link>.</p> :
        zones.map((z) => <label key={z.id} className="flex items-center gap-2 text-sm"><input type="checkbox" checked={p[key].includes(z.id)} onChange={() => toggle(key, other, z.id)} /> {z.name}</label>)}
    </fieldset>
  );

  return (
    <Card className="mb-6" data-testid="auth-policy">
      <CardHeader><CardTitle>Authentication policy</CardTitle></CardHeader>
      <CardContent className="space-y-4 text-sm">
        <p className="text-muted-foreground">Extra conditions for signing in to this application, checked each time a sign-in is completed. Being assigned is still required.</p>
        {msg && <Alert variant={msg.ok ? "default" : "destructive"} role="status"><AlertDescription>{msg.text}</AlertDescription></Alert>}
        <label className="flex items-center gap-2"><input type="checkbox" checked={p.require_mfa} onChange={(e) => setP({ ...p, require_mfa: e.target.checked })} data-testid="policy-mfa" /> Require multi-factor authentication</label>
        <div className="space-y-1"><label htmlFor="policy-reauth" className="font-medium">Require a recent sign-in</label>
          <select id="policy-reauth" className={fieldClass + " w-56"} value={p.reauth_minutes ?? 0} onChange={(e) => setP({ ...p, reauth_minutes: Number(e.target.value) || null })}>
            {REAUTH.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select></div>
        <div className="grid gap-4 sm:grid-cols-2">
          {checks("allowed_zone_ids", "blocked_zone_ids", "Only allow these networks", "When none are ticked, any network is allowed.")}
          {checks("blocked_zone_ids", "allowed_zone_ids", "Always block these networks", "Blocking wins over allowing.")}
        </div>
        <div className="flex gap-2"><SaveButton dirty={dirty} onClick={save} data-testid="policy-save">Save policy</SaveButton>{p.configured && <Button variant="outline" onClick={remove}>Remove policy</Button>}</div>
      </CardContent>
    </Card>
  );
}
