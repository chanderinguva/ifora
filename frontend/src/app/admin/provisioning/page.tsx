"use client";

import { useCallback, useEffect, useState } from "react";
import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge, PageHeader, fieldClass, fmt } from "@/components/bits";
import { useCurrentUser } from "@/components/auth-guard";
import { http } from "@/lib/http";
import type { ScimToken } from "@/lib/types";

const tone = (s: ScimToken["status"]) => (s === "active" ? "good" : "bad");

export default function ProvisioningPage() {
  const me = useCurrentUser();
  const [items, setItems] = useState<ScimToken[] | null>(null);
  const [baseUrl, setBaseUrl] = useState("");
  const [name, setName] = useState<string | null>(null);
  const [days, setDays] = useState("");
  const [readOnly, setReadOnly] = useState(false);
  const [usersOnly, setUsersOnly] = useState(false);
  const [cidrs, setCidrs] = useState("");
  const [retention, setRetention] = useState("");
  const [editing, setEditing] = useState<{ id: number; read_only: boolean; users_only: boolean; cidrs: string; retention: string } | null>(null);
  const [reveal, setReveal] = useState<{ name: string; token: string } | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const load = useCallback(() => {
    http<{ items: ScimToken[]; base_url: string }>("/admin/scim/tokens")
      .then((r) => { setItems(r.items); setBaseUrl(r.base_url); })
      .catch((e) => setMsg({ ok: false, text: e.message }));
  }, []);
  useEffect(load, [load]);

  async function run(fn: () => Promise<unknown>, ok?: string) {
    setMsg(null);
    try {
      await fn();
      if (ok) setMsg({ ok: true, text: ok });
      load();
    } catch (e) {
      setMsg({ ok: false, text: e instanceof Error ? e.message : "Failed" });
    }
  }

  return (
    <div>
      <PageHeader title="Inbound SCIM">
        {me.is_super_admin && <Button onClick={() => setName("")}><Plus className="mr-1 h-4 w-4" /> Create token</Button>}
      </PageHeader>
      <p className="mb-4 max-w-2xl text-sm text-muted-foreground">
        Inbound: let Okta, Microsoft Entra ID or another identity provider create, update and deactivate users and groups here with SCIM 2.0.
        Give the provider the base URL below and a bearer token. Removing a user in the provider deactivates the account; it is never
        deleted. Administrator accounts cannot be changed through SCIM, and users created this way have no password until an administrator
        sets one.
      </p>

      <Card className="mb-6">
        <CardHeader><CardTitle className="text-base">SCIM base URL</CardTitle></CardHeader>
        <CardContent>
          <code className="block break-all rounded bg-muted px-3 py-2 font-mono text-sm select-all" data-testid="scim-base-url">{baseUrl || "…"}</code>
          <p className="mt-2 text-xs text-muted-foreground">
            Supported: Users, Groups, PATCH, filtering (including not, comparisons and valuePath), sorting, POST search, Bulk, attribute projection, ETags. Not supported: password changes, cross-resource search.
          </p>
        </CardContent>
      </Card>

      {msg && <Alert variant={msg.ok ? "default" : "destructive"} className="mb-4" role="status"><AlertDescription>{msg.text}</AlertDescription></Alert>}

      {reveal && (
        <Alert className="mb-4" data-testid="scim-token">
          <AlertDescription className="space-y-2">
            <div>Token <strong>{reveal.name}</strong>. Copy it now; it is shown only once and cannot be recovered.</div>
            <code className="block break-all rounded bg-muted px-3 py-2 font-mono text-sm">{reveal.token}</code>
            <div className="flex gap-2">
              <Button size="sm" variant="outline" onClick={() => navigator.clipboard?.writeText(reveal.token)}>Copy</Button>
              <Button size="sm" onClick={() => setReveal(null)}>I have stored it</Button>
            </div>
          </AlertDescription>
        </Alert>
      )}

      {name !== null && (
        <Card className="mb-6" data-testid="scim-editor">
          <CardHeader><CardTitle>Create token</CardTitle></CardHeader>
          <CardContent className="space-y-4">
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="t-name">Name</Label>
                <Input id="t-name" maxLength={100} placeholder="Okta production" value={name} onChange={(e) => setName(e.target.value)} />
              </div>
              <div className="space-y-2">
                <Label htmlFor="t-days">Expires after (days, optional)</Label>
                <input id="t-days" type="number" min={1} max={3650} className={fieldClass} value={days} onChange={(e) => setDays(e.target.value)} />
              </div>
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={readOnly} onChange={(e) => setReadOnly(e.target.checked)} /> Read-only (cannot create, change or delete)</label>
              <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={usersOnly} onChange={(e) => setUsersOnly(e.target.checked)} /> Users only (no access to Groups)</label>
              <div className="space-y-2">
                <Label htmlFor="t-cidrs">Allowed IP addresses or ranges (optional, comma-separated)</Label>
                <Input id="t-cidrs" placeholder="203.0.113.0/24, 2001:db8::/32" value={cidrs} onChange={(e) => setCidrs(e.target.value)} />
              </div>
              <div className="space-y-2">
                <Label htmlFor="t-ret">Delete deactivated users after (days, optional, 7–3650)</Label>
                <input id="t-ret" type="number" min={7} max={3650} className={fieldClass} value={retention} onChange={(e) => setRetention(e.target.value)} />
              </div>
            </div>
            <p className="text-xs text-muted-foreground">Only super administrators can create tokens: a token can create and deactivate every non-administrator account.</p>
            <div className="flex gap-2">
              <Button disabled={!name.trim()}
                onClick={() => run(async () => {
                  const r = await http<ScimToken>("/admin/scim/tokens", { method: "POST", body: {
                    name, expires_in_days: days ? Number(days) : null, read_only: readOnly, users_only: usersOnly,
                    allowed_cidrs: cidrs.trim() ? cidrs.split(",").map((c) => c.trim()).filter(Boolean) : null,
                    hard_delete_after_days: retention ? Number(retention) : null,
                  } });
                  if (r.token) setReveal({ name: r.name, token: r.token });
                  setName(null); setDays(""); setReadOnly(false); setUsersOnly(false); setCidrs(""); setRetention("");
                }, "Token created")}>
                Create token
              </Button>
              <Button variant="ghost" onClick={() => setName(null)}>Cancel</Button>
            </div>
          </CardContent>
        </Card>
      )}

      {editing && (
        <Card className="mb-6" data-testid="scim-restrictions-editor">
          <CardHeader><CardTitle>Token restrictions</CardTitle></CardHeader>
          <CardContent className="space-y-4">
            <div className="grid gap-4 sm:grid-cols-2">
              <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={editing.read_only} onChange={(e) => setEditing({ ...editing, read_only: e.target.checked })} /> Read-only</label>
              <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={editing.users_only} onChange={(e) => setEditing({ ...editing, users_only: e.target.checked })} /> Users only</label>
              <div className="space-y-2"><Label htmlFor="e-cidrs">Allowed IPs or ranges (empty = any)</Label><Input id="e-cidrs" value={editing.cidrs} onChange={(e) => setEditing({ ...editing, cidrs: e.target.value })} /></div>
              <div className="space-y-2"><Label htmlFor="e-ret">Delete deactivated users after (days; empty = never)</Label><input id="e-ret" type="number" min={7} max={3650} className={fieldClass} value={editing.retention} onChange={(e) => setEditing({ ...editing, retention: e.target.value })} /></div>
            </div>
            <div className="flex gap-2">
              <Button onClick={() => run(async () => {
                await http(`/admin/scim/tokens/${editing.id}/restrictions`, { method: "PUT", body: {
                  read_only: editing.read_only, users_only: editing.users_only,
                  allowed_cidrs: editing.cidrs.trim() ? editing.cidrs.split(",").map((c) => c.trim()).filter(Boolean) : [],
                  hard_delete_after_days: editing.retention ? Number(editing.retention) : 0,
                } });
                setEditing(null);
              }, "Restrictions saved")}>Save</Button>
              <Button variant="ghost" onClick={() => setEditing(null)}>Cancel</Button>
            </div>
          </CardContent>
        </Card>
      )}

      <div className="space-y-3" data-testid="scim-token-list">
        {items?.map((t) => (
          <Card key={t.id}>
            <CardContent className="flex flex-wrap items-center gap-3 py-4 text-sm">
              <strong>{t.name}</strong>
              <Badge tone={tone(t.status)}>{t.status}</Badge>
              <code>{t.token_prefix}…</code>
              <span className="text-muted-foreground">
                created {fmt(t.created_at)} · {t.expires_at ? `expires ${fmt(t.expires_at)}` : "no expiry"} · {t.last_used_at ? `last used ${fmt(t.last_used_at)}` : "never used"}
              </span>
              <span className="basis-full text-xs text-muted-foreground" data-testid="scim-restrictions">
                {[t.read_only && "read-only", t.users_only && "users only", t.allowed_cidrs?.length ? `IPs: ${t.allowed_cidrs.join(", ")}` : "any IP",
                  t.hard_delete_after_days ? `deletes deactivated users after ${t.hard_delete_after_days} days` : "keeps deactivated users"].filter(Boolean).join(" · ")}
                {t.replaced_by_id ? " · replaced by a newer token" : ""}
              </span>
              {t.status === "active" && me.is_super_admin && (
                <div className="ml-auto flex gap-2">
                  <Button size="sm" variant="outline" onClick={() => setEditing({ id: t.id, read_only: !!t.read_only, users_only: !!t.users_only, cidrs: (t.allowed_cidrs ?? []).join(", "), retention: t.hard_delete_after_days ? String(t.hard_delete_after_days) : "" })}>Restrictions</Button>
                  {!t.replaced_by_id && (
                    <Button size="sm" variant="outline"
                      onClick={() => { if (confirm(`Rotate ${t.name}? A new token with the same restrictions is issued; the old one keeps working for 24 hours.`)) run(async () => { const r = await http<ScimToken>(`/admin/scim/tokens/${t.id}/rotate`, { method: "POST", body: { overlap_hours: 24 } }); if (r.token) setReveal({ name: r.name, token: r.token }); }, "Token rotated"); }}>
                      Rotate
                    </Button>
                  )}
                </div>
              )}
              {t.status === "active" && (
                <Button size="sm" variant="outline" className={me.is_super_admin ? "" : "ml-auto"}
                  onClick={() => { if (confirm(`Revoke ${t.name}? The identity provider will stop syncing immediately.`)) run(() => http(`/admin/scim/tokens/${t.id}`, { method: "DELETE" }), "Token revoked"); }}>
                  Revoke
                </Button>
              )}
            </CardContent>
          </Card>
        ))}
        {items && items.length === 0 && <p className="text-sm text-muted-foreground">No tokens yet.</p>}
      </div>
    </div>
  );
}
