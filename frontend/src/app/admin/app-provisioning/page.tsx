"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge, PageHeader, fieldClass } from "@/components/bits";
import { useCurrentUser } from "@/components/auth-guard";
import { http } from "@/lib/http";
import { DEFAULT_OPTIONS, type ProvApp, type ProvPreset } from "@/lib/provisioning";

const status = (a: ProvApp) => (!a.enabled ? { t: "off", tone: "neutral" as const } : a.errors || a.failed_tasks ? { t: "needs attention", tone: "bad" as const } : { t: "active", tone: "good" as const });

export default function ProvisioningApps() {
  const me = useCurrentUser();
  const [apps, setApps] = useState<ProvApp[] | null>(null);
  const [presets, setPresets] = useState<ProvPreset[]>([]);
  const [available, setAvailable] = useState(true);
  const [preset, setPreset] = useState<ProvPreset | null>(null);
  const [form, setForm] = useState({ name: "", base_url: "", auth_type: "bearer", header_name: "", secret: "", client_id: "", token_url: "", scope: "", rest: "" });
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const load = useCallback(() => {
    http<{ items: ProvApp[] }>("/admin/provisioning-apps").then((r) => setApps(r.items)).catch((e) => setMsg({ ok: false, text: e.message }));
    http<{ items: ProvPreset[]; available: boolean }>("/admin/provisioning-apps/presets").then((r) => { setPresets(r.items); setAvailable(r.available); }).catch(() => {});
  }, []);
  useEffect(load, [load]);

  function choose(p: ProvPreset) {
    setPreset(p);
    setForm({ name: "", base_url: "", auth_type: p.auth_type, header_name: "", secret: "", client_id: "", token_url: "", scope: "", rest: p.rest_config ? JSON.stringify(p.rest_config, null, 2) : "" });
  }

  async function create() {
    if (!preset) return;
    setMsg(null);
    try {
      let rest_config: unknown = null;
      if (preset.kind === "rest") {
        try { rest_config = JSON.parse(form.rest); } catch { throw new Error("The gateway operations are not valid JSON"); }
      }
      const created = await http<ProvApp>("/admin/provisioning-apps", { method: "POST", body: {
        name: form.name, kind: preset.kind, base_url: form.base_url, auth_type: form.auth_type,
        header_name: form.auth_type === "header" ? form.header_name : null, secret: form.secret,
        ...(form.auth_type === "oauth2" ? { client_id: form.client_id, token_url: form.token_url, scope: form.scope || null } : {}),
        options: { ...DEFAULT_OPTIONS, ...preset.options }, mapping: [], rest_config,
      } });
      window.location.href = `/admin/app-provisioning/${created.id}`;
    } catch (e) {
      setMsg({ ok: false, text: e instanceof Error ? e.message : "Failed" });
    }
  }

  return (
    <div>
      <PageHeader title="Provisioning apps">
        {me.is_super_admin && available && <Button onClick={() => setPreset(presets[0] ?? null)} data-testid="add-app"><Plus className="mr-1 h-4 w-4" /> Add application</Button>}
      </PageHeader>
      <p className="mb-4 max-w-3xl text-sm text-muted-foreground">
        Push users and groups from IdentityForge to the applications your people use. Applications with a SCIM 2.0 endpoint are provisioned directly;
        for applications with only a REST API, the gateway turns the same lifecycle (create, update, deactivate, delete) into the calls you describe.
        Assign users or groups to an application and it creates, updates and deactivates accounts automatically.
      </p>
      {!available && <Alert variant="destructive" className="mb-4"><AlertDescription>Provisioning apps are unavailable: RECIPE_ENCRYPTION_KEY is not configured on the server.</AlertDescription></Alert>}
      {msg && <Alert variant={msg.ok ? "default" : "destructive"} className="mb-4" role="status"><AlertDescription>{msg.text}</AlertDescription></Alert>}

      {preset && (
        <Card className="mb-6" data-testid="app-editor">
          <CardHeader><CardTitle>Add application</CardTitle></CardHeader>
          <CardContent className="space-y-4">
            <div className="grid gap-3 sm:grid-cols-2">
              {presets.map((p) => (
                <button key={p.key} type="button" onClick={() => choose(p)} aria-pressed={preset.key === p.key}
                  className={`rounded-md border p-3 text-left text-sm hover:bg-accent ${preset.key === p.key ? "border-primary ring-1 ring-primary" : ""}`}>
                  <div className="font-medium">{p.name}</div>
                  <div className="text-xs text-muted-foreground">{p.description}</div>
                </button>
              ))}
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-2"><Label htmlFor="a-name">Name</Label><Input id="a-name" maxLength={100} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></div>
              <div className="space-y-2"><Label htmlFor="a-url">{preset.kind === "scim" ? "SCIM base URL" : "API base URL"} (https)</Label>
                <Input id="a-url" placeholder={preset.kind === "scim" ? "https://app.example.com/scim/v2" : "https://api.example.com"} value={form.base_url} onChange={(e) => setForm({ ...form, base_url: e.target.value })} /></div>
              <div className="space-y-2"><Label htmlFor="a-auth">Authentication</Label>
                <select id="a-auth" className={fieldClass} value={form.auth_type} onChange={(e) => setForm({ ...form, auth_type: e.target.value })}>
                  <option value="bearer">Bearer token</option><option value="basic">Basic (user:password)</option><option value="header">Custom header</option><option value="oauth2">OAuth2 client credentials</option>
                </select></div>
              {form.auth_type === "oauth2" && <>
                <div className="space-y-2"><Label htmlFor="a-cid">Client ID</Label><Input id="a-cid" value={form.client_id} onChange={(e) => setForm({ ...form, client_id: e.target.value })} /></div>
                <div className="space-y-2"><Label htmlFor="a-tok">Token URL (https)</Label><Input id="a-tok" placeholder="https://auth.example.com/oauth/token" value={form.token_url} onChange={(e) => setForm({ ...form, token_url: e.target.value })} /></div>
                <div className="space-y-2"><Label htmlFor="a-scope">Scope (optional)</Label><Input id="a-scope" value={form.scope} onChange={(e) => setForm({ ...form, scope: e.target.value })} /></div></>}
              {form.auth_type === "header" && <div className="space-y-2"><Label htmlFor="a-hdr">Header name</Label><Input id="a-hdr" placeholder="X-API-Key" value={form.header_name} onChange={(e) => setForm({ ...form, header_name: e.target.value })} /></div>}
              <div className="space-y-2"><Label htmlFor="a-secret">{form.auth_type === "basic" ? "user:password" : form.auth_type === "header" ? "Header value" : form.auth_type === "oauth2" ? "Client secret" : "Token"}</Label>
                <Input id="a-secret" type="password" autoComplete="off" value={form.secret} onChange={(e) => setForm({ ...form, secret: e.target.value })} /></div>
            </div>
            {preset.kind === "rest" && (
              <div className="space-y-2">
                <Label htmlFor="a-rest">Gateway operations (JSON)</Label>
                <textarea id="a-rest" rows={14} spellCheck={false} className={`${fieldClass} h-auto font-mono text-xs`} value={form.rest} onChange={(e) => setForm({ ...form, rest: e.target.value })} />
                <p className="text-xs text-muted-foreground">Placeholders like <code>{"{{userName}}"}</code>, <code>{"{{name.givenName}}"}</code>, <code>{"{{active}}"}</code> and <code>{"{{id}}"}</code> (the app&apos;s own id) are filled in. Paths stay on the base URL&apos;s host.</p>
              </div>
            )}
            <p className="text-xs text-muted-foreground">The credential is stored encrypted and never shown again. You can test the connection before anything is sent.</p>
            <div className="flex gap-2">
              <Button disabled={!form.name.trim() || !form.base_url.trim() || !form.secret} onClick={create}>Create</Button>
              <Button variant="ghost" onClick={() => setPreset(null)}>Cancel</Button>
            </div>
          </CardContent>
        </Card>
      )}

      {apps === null ? <p className="text-sm text-muted-foreground">Loading…</p> : apps.length === 0 ? (
        <p className="text-sm text-muted-foreground" data-testid="no-apps">No applications yet.</p>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2" data-testid="app-list">
          {apps.map((a) => {
            const s = status(a);
            return (
              <Link key={a.id} href={`/admin/app-provisioning/${a.id}`} className="rounded-lg border p-4 hover:bg-accent/40">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-medium">{a.name}</span>
                  <Badge tone={s.tone}>{s.t}</Badge>
                </div>
                <div className="mt-1 break-all text-xs text-muted-foreground">{a.kind === "scim" ? "SCIM 2.0" : "REST gateway"} · {a.base_url}</div>
                <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs">
                  <span>{a.provisioned} provisioned</span><span>{a.assigned_users} users, {a.assigned_groups} groups assigned</span>
                  {a.errors > 0 && <span className="text-red-600 dark:text-red-400">{a.errors} with errors</span>}
                  {a.queued > 0 && <span>{a.queued} queued</span>}
                </div>
              </Link>
            );
          })}
        </div>
      )}
    </div>
  );
}
