"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge, PageHeader, fmt } from "@/components/bits";
import { MfaCard } from "@/components/mfa-card";
import { PasskeyCard } from "@/components/passkey-card";
import { http } from "@/lib/http";
import type { User } from "@/lib/types";

type SessionRow = { id: number; created_at: string; expires_at: string; current: boolean; ip_address: string | null; user_agent: string | null };

export default function AccountSettings() {
  const [me, setMe] = useState<User | null>(null);
  const [names, setNames] = useState({ first_name: "", last_name: "" });
  const [attrs, setAttrs] = useState<Record<string, string>>({});
  const [sessions, setSessions] = useState<SessionRow[]>([]);
  const [pw, setPw] = useState({ current_password: "", new_password: "" });
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const apply = (u: User) => {
    setMe(u);
    setNames({ first_name: u.first_name, last_name: u.last_name });
    setAttrs(Object.fromEntries((u.editable_attributes ?? []).map((k) => [k, String(u.profile_attributes?.[k] ?? "")])));
  };
  const loadSessions = () => http<{ items: SessionRow[] }>("/me/sessions").then((r) => setSessions(r.items)).catch(() => {});

  useEffect(() => {
    http<User>("/me/profile").then(apply).catch((e) => setMsg({ ok: false, text: e.message }));
    loadSessions();
  }, []);

  async function run(fn: () => Promise<unknown>, ok: string) {
    setMsg(null);
    try {
      await fn();
      setMsg({ ok: true, text: ok });
    } catch (e) {
      setMsg({ ok: false, text: e instanceof Error ? e.message : "Failed" });
    }
  }

  const changePassword = () =>
    run(async () => {
      await http("/me/password", { method: "POST", body: pw });
      setPw({ current_password: "", new_password: "" });
      loadSessions();
    }, "Password changed; other sessions were signed out");

  if (!me) return <div className="text-sm text-muted-foreground">{msg ? msg.text : "Loading…"}</div>;

  const readOnly = Object.entries(me.profile_attributes ?? {}).filter(([k]) => !(me.editable_attributes ?? []).includes(k));

  return (
    <div className="max-w-3xl">
      <PageHeader title="Account settings">
        {me.is_admin && <Link href="/admin/dashboard" className="text-sm underline-offset-4 hover:underline">Go to administration →</Link>}
      </PageHeader>

      {msg && <Alert variant={msg.ok ? "default" : "destructive"} className="mb-4" role="status"><AlertDescription>{msg.text}</AlertDescription></Alert>}

      <Card className="mb-6">
        <CardHeader><CardTitle>Profile</CardTitle></CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm text-muted-foreground">{me.email} · {me.username}</p>
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="pf-first">First name</Label>
              <Input id="pf-first" value={names.first_name} onChange={(e) => setNames({ ...names, first_name: e.target.value })} />
            </div>
            <div className="space-y-2">
              <Label htmlFor="pf-last">Last name</Label>
              <Input id="pf-last" value={names.last_name} onChange={(e) => setNames({ ...names, last_name: e.target.value })} />
            </div>
            {Object.keys(attrs).map((k) => (
              <div key={k} className="space-y-2">
                <Label htmlFor={`pf-${k}`} className="capitalize">{k}</Label>
                <Input id={`pf-${k}`} value={attrs[k]} onChange={(e) => setAttrs({ ...attrs, [k]: e.target.value })} />
              </div>
            ))}
          </div>
          {readOnly.length > 0 && (
            <div className="text-sm">
              <div className="mb-1 font-medium">Managed by your administrator</div>
              <ul className="text-muted-foreground">
                {readOnly.map(([k, v]) => <li key={k}><span className="capitalize">{k}</span>: {String(v)}</li>)}
              </ul>
            </div>
          )}
          <Button onClick={() => run(async () => apply(await http<User>("/me/profile", { method: "PATCH", body: { ...names, profile_attributes: Object.fromEntries(Object.entries(attrs).filter(([, v]) => v !== "")) } })), "Profile saved")}>
            Save profile
          </Button>
        </CardContent>
      </Card>

      <Card className="mb-6">
        <CardHeader><CardTitle>My groups</CardTitle></CardHeader>
        <CardContent>
          {me.groups && me.groups.length > 0 ? (
            <ul className="flex flex-wrap gap-2">{me.groups.map((g) => <li key={g.id}><Badge tone="info">{g.name}</Badge></li>)}</ul>
          ) : (
            <p className="text-sm text-muted-foreground">You are not a member of any group.</p>
          )}
        </CardContent>
      </Card>

      <h2 className="mb-3 mt-8 text-lg font-semibold" id="security">Security</h2>
      <PasskeyCard />
      <MfaCard />

      <Card className="mb-6">
        <CardHeader><CardTitle>Change password</CardTitle></CardHeader>
        <CardContent>
          <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); changePassword(); }}>
          <div className="space-y-2">
            <Label htmlFor="cur">Current password</Label>
            <Input id="cur" type="password" autoComplete="current-password" value={pw.current_password} onChange={(e) => setPw({ ...pw, current_password: e.target.value })} />
          </div>
          <div className="space-y-2">
            <Label htmlFor="new">New password</Label>
            <Input id="new" type="password" autoComplete="new-password" value={pw.new_password} onChange={(e) => setPw({ ...pw, new_password: e.target.value })} />
            <p className="text-xs text-muted-foreground">12+ characters, mixed case, with a digit. Other devices are signed out.</p>
          </div>
          <Button type="submit" disabled={!pw.current_password || !pw.new_password}>
            Change password
          </Button>
          </form>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>Active sessions</CardTitle></CardHeader>
        <CardContent>
          <ul className="space-y-2 text-sm" data-testid="sessions">
            {sessions.map((s) => (
              <li key={s.id} className="flex flex-wrap items-center gap-2">
                {s.current && <Badge tone="good">this device</Badge>}
                <span>Signed in {fmt(s.created_at)}</span>
                <span className="text-muted-foreground">· {s.ip_address ?? "unknown IP"} · expires {fmt(s.expires_at)}</span>
              </li>
            ))}
          </ul>
        </CardContent>
      </Card>
    </div>
  );
}
