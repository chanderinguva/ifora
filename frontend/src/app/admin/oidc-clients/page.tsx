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

type Draft = { name: string; description: string; client_type: "public" | "confidential" | "service"; redirect_uris: string; post_logout: string; scopes: string[]; first_party: boolean; service_scopes: string; audiences: string; auth_method: "client_secret_basic" | "private_key_jwt"; jwks: string; token_format: "jwt" | "opaque" };
const empty = (): Draft => ({ name: "", description: "", client_type: "public", redirect_uris: "", post_logout: "", scopes: ["openid", "profile", "email"], first_party: false, service_scopes: "", audiences: "", auth_method: "client_secret_basic", jwks: "", token_format: "jwt" });

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
              {me.is_super_admin && (
                <label className="flex items-start gap-2 text-sm">
                  <input type="radio" name="ctype" checked={draft.client_type === "service"} onChange={() => setDraft({ ...draft, client_type: "service" })} />
                  <span><strong>Service</strong> (machine to machine): no user, authenticates with a secret and gets tokens for itself (client credentials).</span>
                </label>
              )}
            </fieldset>
            {draft.client_type !== "public" && (
              <fieldset className="space-y-2">
                <legend className="text-sm font-medium">Client authentication</legend>
                <label className="flex items-start gap-2 text-sm">
                  <input type="radio" name="cauth" checked={draft.auth_method === "client_secret_basic"} onChange={() => setDraft({ ...draft, auth_method: "client_secret_basic" })} />
                  <span><strong>Client secret</strong>: a secret shown once, sent with each token request.</span>
                </label>
                <label className="flex items-start gap-2 text-sm">
                  <input type="radio" name="cauth" checked={draft.auth_method === "private_key_jwt"} onChange={() => setDraft({ ...draft, auth_method: "private_key_jwt" })} />
                  <span><strong>Signed assertion (private_key_jwt)</strong>: the application keeps a private key and signs a short-lived JWT; you register only the public key (RS256 or ES256). Nothing secret is stored here.</span>
                </label>
                {draft.auth_method === "private_key_jwt" && (
                  <div className="space-y-2">
                    <Label htmlFor="c-jwks">Public keys (JWKS JSON, every key needs a kid)</Label>
                    <textarea id="c-jwks" className={fieldClass + " h-28 font-mono"} placeholder='{"keys":[{"kty":"EC","crv":"P-256","kid":"key-1","x":"…","y":"…"}]}' value={draft.jwks} onChange={(e) => setDraft({ ...draft, jwks: e.target.value })} />
                  </div>
                )}
              </fieldset>
            )}
            {draft.client_type === "service" ? (
              <div className="grid gap-4 sm:grid-cols-2">
                <div className="space-y-2">
                  <Label htmlFor="c-sscopes">Scopes (one per line)</Label>
                  <textarea id="c-sscopes" className={fieldClass + " h-24 font-mono"} placeholder="invoices:read" value={draft.service_scopes} onChange={(e) => setDraft({ ...draft, service_scopes: e.target.value })} />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="c-audiences">Audiences / resources (one per line)</Label>
                  <textarea id="c-audiences" className={fieldClass + " h-24 font-mono"} placeholder="https://api.example.com" value={draft.audiences} onChange={(e) => setDraft({ ...draft, audiences: e.target.value })} />
                </div>
              </div>
            ) : (<>
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
            </>)}
            {draft.client_type !== "public" && (
              <label className="flex items-start gap-2 text-sm">
                <input type="checkbox" checked={draft.token_format === "opaque"} onChange={(e) => setDraft({ ...draft, token_format: e.target.checked ? "opaque" : "jwt" })} />
                <span><strong>Opaque access tokens</strong>: random reference tokens instead of JWTs. They can be revoked immediately (<code>/oauth/revoke</code>) and stop working the moment the user is deactivated, but resource servers must call introspection to check them.</span>
              </label>
            )}
            {me.is_super_admin && draft.client_type !== "service" && (
              <label className="flex items-start gap-2 text-sm">
                <input type="checkbox" checked={draft.first_party} onChange={(e) => setDraft({ ...draft, first_party: e.target.checked })} />
                <span><strong>First-party application</strong>: skips the consent screen. Users still have to sign in, and scopes are still limited to the list above. Use only for applications you operate.</span>
              </label>
            )}
            <div className="flex gap-2">
              <Button disabled={!draft.name.trim() || (draft.client_type !== "public" && draft.auth_method === "private_key_jwt" && !draft.jwks.trim()) || (draft.client_type === "service" ? lines(draft.service_scopes).length === 0 || lines(draft.audiences).length === 0 : lines(draft.redirect_uris).length === 0)}
                onClick={() => run(async () => {
                  let jwks: unknown = undefined;
                  if (draft.client_type !== "public" && draft.auth_method === "private_key_jwt") {
                    try { jwks = JSON.parse(draft.jwks); } catch { throw new Error("The public keys must be valid JSON"); }
                  }
                  const r = await http<OidcClient>("/admin/oidc/clients", { method: "POST", body: {
                    ...(draft.client_type !== "public" ? { token_endpoint_auth_method: draft.auth_method } : {}),
                    ...(jwks !== undefined ? { jwks } : {}),
                    name: draft.name, description: draft.description || null, client_type: draft.client_type,
                    redirect_uris: draft.client_type === "service" ? [] : lines(draft.redirect_uris),
                    post_logout_redirect_uris: draft.client_type === "service" ? [] : lines(draft.post_logout),
                    allowed_scopes: draft.client_type === "service" ? lines(draft.service_scopes) : draft.scopes,
                    allowed_audiences: draft.client_type === "service" ? lines(draft.audiences) : [],
                    first_party: draft.client_type === "service" ? false : draft.first_party,
                    access_token_format: draft.client_type === "public" ? "jwt" : draft.token_format,
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
                {c.access_token_format === "opaque" && <Badge tone="info">opaque tokens</Badge>}
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 text-sm">
              {c.description && <p className="text-muted-foreground">{c.description}</p>}
              <div>Client ID: <code className="select-all">{c.client_id}</code></div>
              {c.client_type !== "service" && <div>Redirect URIs: <ul className="ml-4 list-disc font-mono text-xs">{c.redirect_uris.map((u) => <li key={u}>{u}</li>)}</ul></div>}
              {c.client_type === "service" && <div>Audiences: {c.allowed_audiences.map((a) => <code key={a} className="mr-2">{a}</code>)}</div>}
              <div>Scopes: {c.allowed_scopes.map((s) => <code key={s} className="mr-2">{s}</code>)}</div>
              {c.token_endpoint_auth_method === "private_key_jwt" && (
                <div>Signed assertion keys: {c.jwks?.keys.map((k) => <code key={k.kid} className="mr-2">{k.kid} ({k.kty}{k.alg ? `/${k.alg}` : ""})</code>)}</div>
              )}
              {c.token_endpoint_auth_method === "client_secret_basic" && (
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
