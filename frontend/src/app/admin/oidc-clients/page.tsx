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
import type { OidcClient } from "@/lib/types";

const SCOPE_HELP: Record<string, string> = {
  openid: "Sign the user in (required)", profile: "Name and profile attributes", email: "Email address",
  groups: "Group memberships", offline_access: "Refresh tokens (stay signed in)",
};
const lines = (s: string) => s.split("\n").map((x) => x.trim()).filter(Boolean);

type Draft = { name: string; description: string; client_type: "public" | "confidential"; redirect_uris: string; post_logout: string; scopes: string[]; first_party: boolean };
const empty = (): Draft => ({ name: "", description: "", client_type: "public", redirect_uris: "", post_logout: "", scopes: ["openid", "profile", "email"], first_party: false });

export default function OidcClientsPage() {
  const me = useCurrentUser();
  const [items, setItems] = useState<OidcClient[] | null>(null);
  const [scopes, setScopes] = useState<string[]>([]);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [reveal, setReveal] = useState<{ name: string; secret: string } | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const load = useCallback(() => {
    http<{ items: OidcClient[]; supported_scopes: string[] }>("/admin/oidc/clients")
      .then((r) => { setItems(r.items); setScopes(r.supported_scopes); })
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

  const toggle = (list: string[], v: string) => (list.includes(v) ? list.filter((x) => x !== v) : [...list, v]);

  return (
    <div>
      <PageHeader title="OIDC clients">
        <Button onClick={() => setDraft(empty())}><Plus className="mr-1 h-4 w-4" /> Add application</Button>
      </PageHeader>
      <p className="mb-4 max-w-2xl text-sm text-muted-foreground">
        Applications that sign users in with IdentityForge. Every client uses the authorization code flow with PKCE; redirect URIs are
        matched exactly and must be https (http is allowed for localhost only). Sign-in endpoints arrive in a later release.
      </p>

      {msg && <Alert variant={msg.ok ? "default" : "destructive"} className="mb-4" role="status"><AlertDescription>{msg.text}</AlertDescription></Alert>}

      {reveal && (
        <Alert className="mb-4" data-testid="client-secret">
          <AlertDescription className="space-y-2">
            <div>Client secret for <strong>{reveal.name}</strong>. Copy it now; it is shown only once.</div>
            <code className="block break-all rounded bg-muted px-3 py-2 font-mono text-sm">{reveal.secret}</code>
            <div className="flex gap-2">
              <Button size="sm" variant="outline" onClick={() => navigator.clipboard?.writeText(reveal.secret)}>Copy</Button>
              <Button size="sm" onClick={() => setReveal(null)}>I have stored it</Button>
            </div>
          </AlertDescription>
        </Alert>
      )}

      {draft && (
        <Card className="mb-6" data-testid="client-editor">
          <CardHeader><CardTitle>Add application</CardTitle></CardHeader>
          <CardContent className="space-y-4">
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="c-name">Name</Label>
                <Input id="c-name" maxLength={100} value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
              </div>
              <div className="space-y-2">
                <Label htmlFor="c-desc">Description <span className="text-muted-foreground">(optional)</span></Label>
                <Input id="c-desc" maxLength={500} value={draft.description} onChange={(e) => setDraft({ ...draft, description: e.target.value })} />
              </div>
            </div>
            <fieldset className="space-y-2">
              <legend className="text-sm font-medium">Application type</legend>
              <label className="flex items-start gap-2 text-sm">
                <input type="radio" name="ctype" checked={draft.client_type === "public"} onChange={() => setDraft({ ...draft, client_type: "public" })} />
                <span><strong>Public</strong> (single-page or mobile app): cannot keep a secret; PKCE protects the code.</span>
              </label>
              <label className="flex items-start gap-2 text-sm">
                <input type="radio" name="ctype" checked={draft.client_type === "confidential"} onChange={() => setDraft({ ...draft, client_type: "confidential" })} />
                <span><strong>Confidential</strong> (server-side web app): gets a client secret, shown once.</span>
              </label>
            </fieldset>
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="c-redirects">Redirect URIs (one per line)</Label>
                <textarea id="c-redirects" className={fieldClass + " h-24 font-mono"} placeholder="https://app.example.com/callback" value={draft.redirect_uris} onChange={(e) => setDraft({ ...draft, redirect_uris: e.target.value })} />
              </div>
              <div className="space-y-2">
                <Label htmlFor="c-logout">Post-logout redirect URIs (optional)</Label>
                <textarea id="c-logout" className={fieldClass + " h-24 font-mono"} value={draft.post_logout} onChange={(e) => setDraft({ ...draft, post_logout: e.target.value })} />
              </div>
            </div>
            <fieldset className="space-y-2">
              <legend className="text-sm font-medium">Allowed scopes</legend>
              {scopes.map((s) => (
                <label key={s} className="flex items-center gap-2 text-sm">
                  <input type="checkbox" checked={draft.scopes.includes(s)} disabled={s === "openid"} onChange={() => setDraft({ ...draft, scopes: toggle(draft.scopes, s) })} />
                  <code>{s}</code> <span className="text-muted-foreground">{SCOPE_HELP[s]}</span>
                </label>
              ))}
            </fieldset>
            {me.is_super_admin && (
              <label className="flex items-start gap-2 text-sm">
                <input type="checkbox" checked={draft.first_party} onChange={(e) => setDraft({ ...draft, first_party: e.target.checked })} />
                <span><strong>First-party application</strong>: skips the consent screen. Users still have to sign in, and scopes are still limited to the list above. Use only for applications you operate.</span>
              </label>
            )}
            <div className="flex gap-2">
              <Button disabled={!draft.name.trim() || lines(draft.redirect_uris).length === 0}
                onClick={() => run(async () => {
                  const r = await http<OidcClient>("/admin/oidc/clients", { method: "POST", body: {
                    name: draft.name, description: draft.description || null, client_type: draft.client_type,
                    redirect_uris: lines(draft.redirect_uris), post_logout_redirect_uris: lines(draft.post_logout),
                    allowed_scopes: draft.scopes, first_party: draft.first_party,
                  } });
                  if (r.client_secret) setReveal({ name: r.name, secret: r.client_secret });
                  setDraft(null);
                }, "Application created")}>
                Create application
              </Button>
              <Button variant="ghost" onClick={() => setDraft(null)}>Cancel</Button>
            </div>
          </CardContent>
        </Card>
      )}

      <div className="space-y-4" data-testid="client-list">
        {items?.map((c) => (
          <Card key={c.id}>
            <CardHeader>
              <CardTitle className="flex flex-wrap items-center gap-2 text-base">
                {c.name}
                <Badge tone={c.status === "active" ? "good" : "bad"}>{c.status}</Badge>
                <Badge>{c.client_type}</Badge>
                {c.first_party && <Badge tone="info">first-party</Badge>}
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 text-sm">
              {c.description && <p className="text-muted-foreground">{c.description}</p>}
              <div>Client ID: <code className="select-all">{c.client_id}</code></div>
              <div>Redirect URIs: <ul className="ml-4 list-disc font-mono text-xs">{c.redirect_uris.map((u) => <li key={u}>{u}</li>)}</ul></div>
              <div>Scopes: {c.allowed_scopes.map((s) => <code key={s} className="mr-2">{s}</code>)}</div>
              {c.client_type === "confidential" && (
                <div className="space-y-2">
                  <div className="font-medium">Client secrets</div>
                  <ul className="space-y-1">
                    {c.secrets.map((s) => (
                      <li key={s.id} className="flex flex-wrap items-center gap-2">
                        <code>…{s.hint}</code>
                        <Badge tone={s.state === "active" ? "good" : "neutral"}>{s.state}</Badge>
                        <span className="text-muted-foreground">created {fmt(s.created_at)}{s.last_used_at ? ` · last used ${fmt(s.last_used_at)}` : " · never used"}</span>
                        {s.state === "active" && (
                          <Button size="sm" variant="outline" onClick={() => { if (confirm("Revoke this secret? Applications using it will stop working.")) run(() => http(`/admin/oidc/clients/${c.id}/secrets/${s.id}`, { method: "DELETE" }), "Secret revoked"); }}>Revoke</Button>
                        )}
                      </li>
                    ))}
                  </ul>
                  <Button size="sm" variant="secondary"
                    onClick={() => run(async () => { const r = await http<OidcClient>(`/admin/oidc/clients/${c.id}/secrets`, { method: "POST", body: {} }); if (r.client_secret) setReveal({ name: c.name, secret: r.client_secret }); })}>
                    Add secret (rotation)
                  </Button>
                  <p className="text-xs text-muted-foreground">Up to two secrets can be active so you can rotate without downtime: add a new one, deploy it, then revoke the old one.</p>
                </div>
              )}
              <div className="flex gap-2 pt-1">
                <Button size="sm" variant="outline" onClick={() => run(() => http(`/admin/oidc/clients/${c.id}`, { method: "PATCH", body: { status: c.status === "active" ? "disabled" : "active" } }))}>
                  {c.status === "active" ? "Disable" : "Enable"}
                </Button>
                <Button size="sm" variant="outline" onClick={() => { if (confirm(`Delete ${c.name}? This cannot be undone.`)) run(() => http(`/admin/oidc/clients/${c.id}`, { method: "DELETE" }), "Application deleted"); }}>Delete</Button>
              </div>
            </CardContent>
          </Card>
        ))}
        {items && items.length === 0 && <p className="text-sm text-muted-foreground">No applications yet.</p>}
      </div>
    </div>
  );
}
