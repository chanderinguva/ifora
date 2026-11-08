"use client";

import { useCallback, useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { fieldClass } from "@/components/bits";
import { http } from "@/lib/http";

type Extra = { name: string; value: string };
type Cfg = { login_url: string; username_field: string; password_field: string; extra_fields: Extra[]; username_source: string };
type Info = { config: Cfg | null; vault_enabled: boolean; credentials: number };
type Row = { user_id: number; email: string; username: string | null; updated_at: string; last_used_at: string | null };
const blank: Cfg = { login_url: "", username_field: "username", password_field: "password", extra_fields: [], username_source: "user" };

/** Secure Web Authentication settings (ADR 012): where the application's login form posts to, and which fields it expects. */
export function SwaCard({ appId, onChange }: { appId: number; onChange: () => void }) {
  const [info, setInfo] = useState<Info | null>(null);
  const [f, setF] = useState<Cfg>(blank);
  const [rows, setRows] = useState<Row[]>([]);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const load = useCallback(() => {
    http<Info>(`/admin/applications/${appId}/swa`).then((i) => { setInfo(i); if (i.config) setF(i.config); }).catch((e) => setMsg({ ok: false, text: e.message }));
    http<{ items: Row[] }>(`/admin/applications/${appId}/swa/credentials`).then((r) => setRows(r.items)).catch(() => {});
  }, [appId]);
  useEffect(load, [load]);

  async function run(fn: () => Promise<unknown>, ok: string) {
    setMsg(null);
    try { await fn(); setMsg({ ok: true, text: ok }); load(); onChange(); } catch (e) { setMsg({ ok: false, text: e instanceof Error ? e.message : "Failed" }); }
  }
  const set = (p: Partial<Cfg>) => setF({ ...f, ...p });
  const setExtra = (i: number, p: Partial<Extra>) => set({ extra_fields: f.extra_fields.map((x, j) => (j === i ? { ...x, ...p } : x)) });

  return (
    <Card className="mb-6" data-testid="swa-card">
      <CardHeader>
        <CardTitle>Secure Web Authentication</CardTitle>
        <CardDescription>
          For applications that only have a username and password form. Each user stores their own account once; IdentityForge keeps the password encrypted and posts it
          to the login URL below when they open the tile. Only use this for applications that cannot do SAML or OpenID Connect.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {info && !info.vault_enabled && (
          <Alert variant="destructive" data-testid="swa-vault-off"><AlertDescription>Stored credentials are disabled: set <code>SWA_ENCRYPTION_KEY</code> on the server. Users cannot save passwords until then.</AlertDescription></Alert>
        )}
        {msg && <Alert variant={msg.ok ? "default" : "destructive"} role="status"><AlertDescription>{msg.text}</AlertDescription></Alert>}
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="space-y-1 sm:col-span-2"><Label htmlFor="swa-url">Login URL (the form's action)</Label>
            <Input id="swa-url" placeholder="https://legacy.example.com/login.php" value={f.login_url} onChange={(e) => set({ login_url: e.target.value })} />
            <p className="text-xs text-muted-foreground">https only. Passwords are sent here and nowhere else. Changing it removes every stored password.</p></div>
          <div className="space-y-1"><Label htmlFor="swa-uf">Username field name</Label><Input id="swa-uf" value={f.username_field} onChange={(e) => set({ username_field: e.target.value })} /></div>
          <div className="space-y-1"><Label htmlFor="swa-pf">Password field name</Label><Input id="swa-pf" value={f.password_field} onChange={(e) => set({ password_field: e.target.value })} /></div>
          <div className="space-y-1"><Label htmlFor="swa-src">Username</Label>
            <select id="swa-src" className={fieldClass} value={f.username_source} onChange={(e) => set({ username_source: e.target.value })}>
              <option value="user">Each user enters it</option>
              <option value="email">Their IdentityForge email</option>
              <option value="username">Their IdentityForge username</option>
            </select></div>
        </div>
        <div className="space-y-2">
          <Label>Extra fixed fields (hidden inputs the form needs)</Label>
          {f.extra_fields.map((x, i) => (
            <div key={i} className="flex gap-2">
              <Input aria-label={`Extra field ${i + 1} name`} placeholder="name" value={x.name} onChange={(e) => setExtra(i, { name: e.target.value })} />
              <Input aria-label={`Extra field ${i + 1} value`} placeholder="value" value={x.value} onChange={(e) => setExtra(i, { value: e.target.value })} />
              <Button variant="outline" onClick={() => set({ extra_fields: f.extra_fields.filter((_, j) => j !== i) })}>Remove</Button>
            </div>
          ))}
          {f.extra_fields.length < 10 && <Button variant="outline" onClick={() => set({ extra_fields: [...f.extra_fields, { name: "", value: "" }] })}>Add field</Button>}
        </div>
        <div className="flex gap-2">
          <Button onClick={() => run(() => http(`/admin/applications/${appId}/swa`, { method: "PUT", body: f }), "SWA settings saved")}>Save SWA settings</Button>
          {info?.config && <Button variant="destructive" onClick={() => { if (confirm("Remove the SWA settings and every stored password?")) run(() => http(`/admin/applications/${appId}/swa`, { method: "DELETE" }), "SWA settings removed"); }}>Remove</Button>}
        </div>
        {info?.config && (
          <div className="space-y-2" data-testid="swa-credentials">
            <h3 className="text-sm font-medium">Stored sign-ins ({rows.length})</h3>
            <p className="text-xs text-muted-foreground">Administrators cannot see passwords. Reset removes a user's stored sign-in so they enter it again.</p>
            {rows.length === 0 ? <p className="text-sm text-muted-foreground">No user has stored a password yet.</p> : (
              <ul className="divide-y rounded-md border text-sm">
                {rows.map((r) => (
                  <li key={r.user_id} className="flex items-center justify-between gap-2 p-2">
                    <span>{r.email}{r.username ? ` (${r.username})` : ""} <span className="text-xs text-muted-foreground">· {r.last_used_at ? `last used ${new Date(r.last_used_at).toLocaleDateString()}` : "never used"}</span></span>
                    <Button variant="outline" onClick={() => run(() => http(`/admin/applications/${appId}/swa/credentials/${r.user_id}`, { method: "DELETE" }), "Stored sign-in reset")}>Reset</Button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
