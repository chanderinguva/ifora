"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge, PageHeader, fieldClass, td, th } from "@/components/bits";
import { http, qs } from "@/lib/http";
import { SIGN_ON_LABEL, type AppSummary, type Template } from "@/lib/applications";

export default function Applications() {
  const router = useRouter();
  const [items, setItems] = useState<AppSummary[] | null>(null);
  const [q, setQ] = useState("");
  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState({ kind: "bookmark", name: "", launch_url: "", redirects: "", initiate: "", audiences: "", require_assignment: true });
  const [templates, setTemplates] = useState<Template[]>([]);
  const [created, setCreated] = useState<{ id: number; client_id: string; secret?: string } | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  useEffect(() => { http<{ items: Template[] }>("/admin/applications/templates").then((r) => setTemplates(r.items)).catch(() => {}); }, []);
  const tpl = templates.find((t) => t.id === form.kind);
  const lines = (v: string) => v.split("\n").map((x) => x.trim()).filter(Boolean);

  const load = useCallback(() => {
    http<{ items: AppSummary[] }>(`/admin/applications${qs({ q })}`).then((r) => setItems(r.items)).catch((e) => setMsg(e.message));
  }, [q]);
  useEffect(load, [load]);

  async function create() {
    setMsg(null);
    try {
      if (tpl) {
        const c = await http<{ application_id: number; client_id: string; client_secret?: string }>("/admin/applications/from-template", { method: "POST", body: {
          template: tpl.id, name: form.name, launch_url: form.launch_url || null, initiate_login_uri: form.initiate || null,
          redirect_uris: lines(form.redirects), allowed_audiences: lines(form.audiences), require_assignment: form.require_assignment } });
        setCreated({ id: c.application_id, client_id: c.client_id, secret: c.client_secret });
        return;
      }
      const a = await http<AppSummary>("/admin/applications", { method: "POST", body: { name: form.name, sign_on_mode: form.kind, launch_url: form.kind === "none" ? null : form.launch_url || null } });
      router.push(`/admin/applications/${a.id}`);
    } catch (e) { setMsg(e instanceof Error ? e.message : "Failed"); }
  }

  return (
    <div>
      <PageHeader title="Applications">
        <Button onClick={() => setAdding(true)}><Plus className="mr-1 h-4 w-4" /> Add application</Button>
      </PageHeader>
      <p className="mb-4 max-w-2xl text-sm text-muted-foreground">
        One application holds who may use it (users and groups). Attach a sign-on method (a bookmark or an OpenID Connect client) and, optionally, outbound provisioning to it.
      </p>
      {msg && <Alert variant="destructive" className="mb-4" role="status"><AlertDescription>{msg}</AlertDescription></Alert>}

      {created && (
        <Alert className="mb-6" data-testid="app-created">
          <AlertDescription className="space-y-2">
            <div>Application created. Client ID: <code>{created.client_id}</code></div>
            {created.secret ? <div>Client secret (shown only once — copy it now): <code className="break-all" data-testid="new-secret">{created.secret}</code></div> : <div>This client has no secret.</div>}
            <Button size="sm" onClick={() => router.push(`/admin/applications/${created.id}`)}>Continue to the application</Button>
          </AlertDescription>
        </Alert>
      )}

      {adding && !created && (
        <Card className="mb-6" data-testid="app-create"><CardContent className="grid gap-3 pt-6 sm:grid-cols-2">
          <div className="space-y-1 sm:col-span-2"><Label htmlFor="a-kind">Type</Label>
            <select id="a-kind" className={fieldClass} value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value })}>
              <option value="bookmark">Bookmark (a link on the user&apos;s My apps page)</option>
              {templates.map((t) => <option key={t.id} value={t.id}>OIDC · {t.label}</option>)}
              <option value="saml">SAML 2.0</option>
              <option value="none">Provisioning only (no sign-on)</option>
            </select>
            {tpl && <p className="text-xs text-muted-foreground">{tpl.description}</p>}</div>
          <div className="space-y-1"><Label htmlFor="a-name">Name</Label><Input id="a-name" value={form.name} maxLength={100} onChange={(e) => setForm({ ...form, name: e.target.value })} /></div>
          {form.kind !== "none" && form.kind !== "service" && form.kind !== "saml" && (
            <div className="space-y-1"><Label htmlFor="a-url">Launch URL{form.kind === "bookmark" ? "" : " (home page, optional)"}</Label>
              <Input id="a-url" placeholder="https://app.example.com/" value={form.launch_url} onChange={(e) => setForm({ ...form, launch_url: e.target.value })} /></div>
          )}
          {tpl?.needs_redirects && (
            <div className="space-y-1 sm:col-span-2"><Label htmlFor="a-redirects">Sign-in redirect URIs (one per line)</Label>
              <textarea id="a-redirects" rows={3} className={fieldClass} placeholder="https://app.example.com/callback" value={form.redirects} onChange={(e) => setForm({ ...form, redirects: e.target.value })} /></div>
          )}
          {tpl && tpl.id !== "service" && (
            <div className="space-y-1 sm:col-span-2"><Label htmlFor="a-init">Initiate login URI (optional)</Label>
              <Input id="a-init" placeholder="https://app.example.com/login" value={form.initiate} onChange={(e) => setForm({ ...form, initiate: e.target.value })} />
              <p className="text-xs text-muted-foreground">When set, clicking the tile sends the user there with <code>iss</code> so the app starts a normal sign-in (IdP-initiated launch).</p></div>
          )}
          {tpl?.id === "service" && (
            <div className="space-y-1 sm:col-span-2"><Label htmlFor="a-aud">Audiences (one per line)</Label>
              <textarea id="a-aud" rows={2} className={fieldClass} placeholder="https://api.example.com" value={form.audiences} onChange={(e) => setForm({ ...form, audiences: e.target.value })} /></div>
          )}
          {tpl && tpl.id !== "service" && (
            <label className="flex items-center gap-2 text-sm sm:col-span-2"><input type="checkbox" checked={form.require_assignment} onChange={(e) => setForm({ ...form, require_assignment: e.target.checked })} /> Only assigned users may sign in</label>
          )}
          <div className="flex gap-2 sm:col-span-2">
            <Button disabled={!form.name.trim() || (form.kind === "bookmark" && !form.launch_url.trim()) || (!!tpl?.needs_redirects && lines(form.redirects).length === 0)} onClick={create}>Create</Button>
            <Button variant="ghost" onClick={() => setAdding(false)}>Cancel</Button>
          </div>
        </CardContent></Card>
      )}

      <div className="mb-3 max-w-xs"><Input aria-label="Search applications" placeholder="Search…" value={q} onChange={(e) => setQ(e.target.value)} /></div>
      <Card><CardContent className="overflow-x-auto p-0">
        <table className="w-full" data-testid="apps-table">
          <thead className="border-b"><tr><th className={th}>Name</th><th className={th}>Sign-on</th><th className={th}>Provisioning</th><th className={th}>Assigned</th><th className={th}>Status</th></tr></thead>
          <tbody>
            {items?.map((a) => (
              <tr key={a.id} className="border-b last:border-0">
                <td className={td + " font-medium"}><Link className="underline-offset-4 hover:underline" href={`/admin/applications/${a.id}`}>{a.name}</Link></td>
                <td className={td}>{SIGN_ON_LABEL[a.sign_on_mode]}</td>
                <td className={td}>{a.provisioning ? <Badge tone={a.provisioning.enabled ? "good" : "neutral"}>{a.provisioning.kind.toUpperCase()}{a.provisioning.enabled ? "" : " (off)"}</Badge> : "—"}</td>
                <td className={td}>{a.assigned_users} users, {a.assigned_groups} groups</td>
                <td className={td}><Badge tone={a.status === "active" ? "good" : "neutral"}>{a.status}</Badge></td>
              </tr>
            ))}
            {items && items.length === 0 && <tr><td className={td} colSpan={5}>No applications yet.</td></tr>}
          </tbody>
        </table>
      </CardContent></Card>
    </div>
  );
}
