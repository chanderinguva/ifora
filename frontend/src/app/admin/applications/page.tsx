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
import { SIGN_ON_LABEL, type AppSummary } from "@/lib/applications";

export default function Applications() {
  const router = useRouter();
  const [items, setItems] = useState<AppSummary[] | null>(null);
  const [q, setQ] = useState("");
  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState({ name: "", sign_on_mode: "bookmark", launch_url: "" });
  const [msg, setMsg] = useState<string | null>(null);

  const load = useCallback(() => {
    http<{ items: AppSummary[] }>(`/admin/applications${qs({ q })}`).then((r) => setItems(r.items)).catch((e) => setMsg(e.message));
  }, [q]);
  useEffect(load, [load]);

  async function create() {
    setMsg(null);
    try {
      const a = await http<AppSummary>("/admin/applications", { method: "POST", body: { name: form.name, sign_on_mode: form.sign_on_mode, launch_url: form.sign_on_mode === "none" ? null : form.launch_url || null } });
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

      {adding && (
        <Card className="mb-6" data-testid="app-create"><CardContent className="grid gap-3 pt-6 sm:grid-cols-2">
          <div className="space-y-1"><Label htmlFor="a-name">Name</Label><Input id="a-name" value={form.name} maxLength={100} onChange={(e) => setForm({ ...form, name: e.target.value })} /></div>
          <div className="space-y-1"><Label htmlFor="a-mode">Sign-on method</Label>
            <select id="a-mode" className={fieldClass} value={form.sign_on_mode} onChange={(e) => setForm({ ...form, sign_on_mode: e.target.value })}>
              <option value="bookmark">Bookmark (a link on the user's My apps page)</option>
              <option value="oidc">OpenID Connect</option>
              <option value="none">None (provisioning only)</option>
            </select></div>
          {form.sign_on_mode !== "none" && (
            <div className="space-y-1 sm:col-span-2"><Label htmlFor="a-url">Launch URL{form.sign_on_mode === "bookmark" ? "" : " (optional)"}</Label>
              <Input id="a-url" placeholder="https://app.example.com/" value={form.launch_url} onChange={(e) => setForm({ ...form, launch_url: e.target.value })} /></div>
          )}
          <div className="flex gap-2 sm:col-span-2">
            <Button disabled={!form.name.trim() || (form.sign_on_mode === "bookmark" && !form.launch_url.trim())} onClick={create}>Create</Button>
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
