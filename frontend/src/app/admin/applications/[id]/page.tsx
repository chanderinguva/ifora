"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge, PageHeader, fieldClass } from "@/components/bits";
import { AppIcon } from "@/components/app-icon";
import { SamlCard } from "@/components/saml-card";
import { SwaCard } from "@/components/swa-card";
import { AuthPolicyCard } from "@/components/auth-policy-card";
import { http, qs, type Page } from "@/lib/http";
import { appBody, SIGN_ON_LABEL, type AppSummary } from "@/lib/applications";
import type { Group, User } from "@/lib/types";

type Assignment = { id: number; type: "user" | "group"; subject_id: number; name: string; detail: string };
type ClientRow = { id: number; client_id: string; name: string; application_id: number | null; initiate_login_uri: string | null; client_type: string };

const TABS = [["general", "General"], ["signon", "Sign On"], ["provisioning", "Provisioning"], ["assignments", "Assignments"]] as const;
type Tab = (typeof TABS)[number][0];

export default function ApplicationDetail() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [app, setApp] = useState<AppSummary | null>(null);
  const [form, setForm] = useState<AppSummary | null>(null);
  const [assignments, setAssignments] = useState<Assignment[]>([]);
  const [users, setUsers] = useState<User[]>([]);
  const [groups, setGroups] = useState<Group[]>([]);
  const [clients, setClients] = useState<ClientRow[]>([]);
  const [pickUser, setPickUser] = useState("");
  const [pickGroup, setPickGroup] = useState("");
  const [pickClient, setPickClient] = useState("");
  const [iconRev, setIconRev] = useState(0);
  const [initiate, setInitiate] = useState<string | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [tab, setTab] = useState<Tab>("general");
  useEffect(() => { const h = window.location.hash.slice(1) as Tab; if (TABS.some(([k]) => k === h)) setTab(h); }, []);
  const pickTab = (k: Tab) => { setTab(k); window.history.replaceState(null, "", `#${k}`); };

  const refresh = useCallback(() => {
    http<AppSummary>(`/admin/applications/${id}`).then((a) => { setApp(a); setForm(a); }).catch((e) => setMsg({ ok: false, text: e.message }));
    http<{ items: Assignment[] }>(`/admin/applications/${id}/assignments`).then((r) => setAssignments(r.items)).catch(() => {});
    http<{ items: ClientRow[] }>("/admin/oidc/clients").then((r) => setClients(r.items)).catch(() => {});
  }, [id]);
  useEffect(() => {
    refresh();
    http<Page<User>>(`/admin/users${qs({ page_size: 100 })}`).then((p) => setUsers(p.items)).catch(() => {});
    http<Page<Group>>(`/admin/groups${qs({ page_size: 100 })}`).then((p) => setGroups(p.items)).catch(() => {});
  }, [refresh]);

  async function run(fn: () => Promise<unknown>, ok?: string) {
    setMsg(null);
    try { await fn(); if (ok) setMsg({ ok: true, text: ok }); refresh(); } catch (e) { setMsg({ ok: false, text: e instanceof Error ? e.message : "Failed" }); }
  }

  async function uploadIcon(f: File) {
    if (f.size > 100 * 1024) { setMsg({ ok: false, text: "The logo must be at most 100 KB" }); return; }
    const bytes = new Uint8Array(await f.arrayBuffer());
    let bin = "";
    bytes.forEach((b) => { bin += String.fromCharCode(b); });
    await run(async () => { await http(`/admin/applications/${id}/icon`, { method: "PUT", body: { data: btoa(bin) } }); setIconRev((n) => n + 1); }, "Logo saved");
  }

  if (!app || !form) return <div className="text-sm text-muted-foreground">{msg ? msg.text : "Loading…"}</div>;
  const assignedUsers = new Set(assignments.filter((a) => a.type === "user").map((a) => a.subject_id));
  const assignedGroups = new Set(assignments.filter((a) => a.type === "group").map((a) => a.subject_id));
  const freeClients = clients.filter((c) => c.application_id == null);
  const set = (p: Partial<AppSummary>) => setForm({ ...form, ...p });

  return (
    <div className="max-w-4xl">
      <PageHeader title={app.name}>
        <Badge tone={app.status === "active" ? "good" : "neutral"}>{app.status}</Badge>
        <Link href="/admin/applications" className="text-sm underline-offset-4 hover:underline">← All applications</Link>
      </PageHeader>
      <div role="tablist" aria-label="Application sections" className="mb-6 flex gap-1 border-b">
        {TABS.map(([k, l]) => (
          <button key={k} role="tab" type="button" aria-selected={tab === k} data-testid={`tab-${k}`} onClick={() => pickTab(k)}
            className={`-mb-px border-b-2 px-4 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${tab === k ? "border-primary font-medium" : "border-transparent text-muted-foreground hover:text-foreground"}`}>{l}</button>
        ))}
      </div>
      {msg && <Alert variant={msg.ok ? "default" : "destructive"} className="mb-4" role="status"><AlertDescription>{msg.text}</AlertDescription></Alert>}

      {tab === "general" && (<>
      <Card className="mb-6">
        <CardHeader><CardTitle>General</CardTitle></CardHeader>
        <CardContent className="grid gap-3 sm:grid-cols-2">
          <div className="space-y-1"><Label htmlFor="g-name">Name</Label><Input id="g-name" value={form.name} maxLength={100} onChange={(e) => set({ name: e.target.value })} /></div>
          <div className="space-y-1"><Label htmlFor="g-mode">Sign-on method</Label>
            <select id="g-mode" className={fieldClass} value={form.sign_on_mode} onChange={(e) => set({ sign_on_mode: e.target.value as AppSummary["sign_on_mode"] })}>
              {Object.entries(SIGN_ON_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select></div>
          <div className="space-y-1 sm:col-span-2"><Label htmlFor="g-desc">Description</Label><Input id="g-desc" value={form.description ?? ""} maxLength={500} onChange={(e) => set({ description: e.target.value })} /></div>
          {form.sign_on_mode !== "none" && form.sign_on_mode !== "saml" && form.sign_on_mode !== "swa" && (
            <div className="space-y-1 sm:col-span-2"><Label htmlFor="g-url">Launch URL</Label><Input id="g-url" placeholder="https://app.example.com/" value={form.launch_url ?? ""} onChange={(e) => set({ launch_url: e.target.value })} /></div>
          )}
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={form.status === "active"} onChange={(e) => set({ status: e.target.checked ? "active" : "inactive" })} /> Active (an inactive application cannot be used to sign in or launched)</label>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={form.visible} onChange={(e) => set({ visible: e.target.checked })} /> Show on users' My apps page</label>
          <label className="flex items-center gap-2 text-sm sm:col-span-2"><input type="checkbox" checked={form.require_assignment} onChange={(e) => set({ require_assignment: e.target.checked })} /> Only assigned users may sign in with this application</label>
          <div className="flex gap-2 sm:col-span-2">
            <Button onClick={() => run(() => http(`/admin/applications/${id}`, { method: "PUT", body: appBody(form) }), "Saved")}>Save</Button>
            <Button variant="destructive" onClick={() => { if (confirm(`Delete ${app.name}?`)) run(async () => { await http(`/admin/applications/${id}`, { method: "DELETE" }); router.push("/admin/applications"); }); }}>Delete</Button>
          </div>
        </CardContent>
      </Card>

      <Card className="mb-6" data-testid="icon-card">
        <CardHeader><CardTitle>Logo</CardTitle></CardHeader>
        <CardContent className="flex flex-wrap items-center gap-4 text-sm">
          <AppIcon key={`${app.has_icon}-${iconRev}`} path={`/admin/applications/${id}/icon?v=${iconRev}`} name={app.name} hasIcon={app.has_icon} size={64} />
          <div className="space-y-2">
            <p className="text-muted-foreground">PNG, JPEG or WebP, at most 100 KB; square works best. Shown on users&apos; My apps tiles.</p>
            <div className="flex flex-wrap items-center gap-2">
              <input type="file" aria-label="Upload logo" accept="image/png,image/jpeg,image/webp" onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) uploadIcon(f); }} />
              {app.has_icon && <Button size="sm" variant="outline" onClick={() => run(async () => { await http(`/admin/applications/${id}/icon`, { method: "DELETE" }); setIconRev((n) => n + 1); }, "Logo removed")}>Remove logo</Button>}
            </div>
          </div>
        </CardContent>
      </Card>

      </>)}

      {tab === "signon" && (<>
      {app.sign_on_mode === "oidc" && (
        <Card className="mb-6" data-testid="oidc-facet">
          <CardHeader><CardTitle>OpenID Connect client</CardTitle></CardHeader>
          <CardContent className="space-y-3 text-sm">
            {app.oidc_client ? (<>
              <div className="flex items-center justify-between gap-2">
                <span><span className="font-medium">{app.oidc_client.name}</span> <code className="text-xs">{app.oidc_client.client_id}</code></span>
                <span className="space-x-2">
                  <Link href="/admin/oidc-clients" className="underline underline-offset-4">Manage clients</Link>
                  <Button size="sm" variant="outline" onClick={() => run(() => http(`/admin/applications/${id}/oidc-client`, { method: "DELETE" }), "Client detached")}>Detach</Button>
                </span>
              </div>
              {app.oidc_client.client_type !== "service" && (() => {
                const cur = clients.find((c) => c.id === app.oidc_client!.id)?.initiate_login_uri ?? "";
                const val = initiate ?? cur;
                return (
                  <div className="space-y-1">
                    <Label htmlFor="g-init">Initiate login URI (IdP-initiated launch)</Label>
                    <div className="flex gap-2">
                      <Input id="g-init" placeholder="https://app.example.com/login" value={val} onChange={(e) => setInitiate(e.target.value)} />
                      <Button size="sm" variant="outline" disabled={val === cur} onClick={() => run(async () => { await http(`/admin/oidc/clients/${app.oidc_client!.id}`, { method: "PATCH", body: { initiate_login_uri: val } }); setInitiate(null); }, "Saved")}>Save</Button>
                    </div>
                    <p className="text-xs text-muted-foreground">The tile opens this URL with <code>iss</code> (and <code>target_link_uri</code> = the launch URL). The app must then start a standard authorization-code flow with PKCE.</p>
                  </div>
                );
              })()}
            </>) : (
              <div className="flex flex-wrap gap-2">
                <select aria-label="Attach a client" className={`${fieldClass} w-72`} value={pickClient} onChange={(e) => setPickClient(e.target.value)}>
                  <option value="">Attach an existing client…</option>
                  {freeClients.map((c) => <option key={c.id} value={c.id}>{c.name} ({c.client_id})</option>)}
                </select>
                <Button size="sm" disabled={!pickClient} onClick={() => run(async () => { await http(`/admin/applications/${id}/oidc-client`, { method: "POST", body: { client_pk: Number(pickClient) } }); setPickClient(""); }, "Client attached")}>Attach</Button>
                <Link href="/admin/oidc-clients" className="self-center underline underline-offset-4">or register a new client</Link>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {app.sign_on_mode === "saml" && <SamlCard appId={app.id} onChange={refresh} />}
      {app.sign_on_mode === "swa" && <SwaCard appId={app.id} onChange={refresh} />}
      {(app.sign_on_mode === "oidc" || app.sign_on_mode === "saml" || app.sign_on_mode === "swa") && <AuthPolicyCard appId={app.id} />}
      {(app.sign_on_mode === "bookmark" || app.sign_on_mode === "none") && <p className="mb-6 text-sm text-muted-foreground" data-testid="no-signon">{app.sign_on_mode === "bookmark" ? "A bookmark app has no single sign-on settings; users open the launch URL set under General." : "This application has no sign-on method; it only provisions users."}</p>}

      </>)}

      {tab === "provisioning" && (<>
      <Card className="mb-6" data-testid="provisioning-facet">
        <CardHeader><CardTitle>Provisioning</CardTitle></CardHeader>
        <CardContent className="text-sm">
          {app.provisioning
            ? <span>Outbound {app.provisioning.kind.toUpperCase()} provisioning is configured <Badge tone={app.provisioning.enabled ? "good" : "neutral"}>{app.provisioning.enabled ? "on" : "off"}</Badge> · <Link href={`/admin/app-provisioning/${app.provisioning.id}`} className="underline underline-offset-4">Open</Link></span>
            : <span className="text-muted-foreground">Not configured. Provisioning apps are created under <Link href="/admin/app-provisioning" className="underline underline-offset-4">Provisioning apps</Link>; they share this application&apos;s assignments.</span>}
        </CardContent>
      </Card>

      </>)}

      {tab === "assignments" && (<>
      <Card className="mb-6">
        <CardHeader><CardTitle>Assignments</CardTitle></CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm text-muted-foreground">Assigned users and every member of an assigned group may use the application; the same list drives provisioning. Only active users count.</p>
          <div className="flex flex-wrap gap-2">
            <select aria-label="Assign a user" className={`${fieldClass} w-64`} value={pickUser} onChange={(e) => setPickUser(e.target.value)}>
              <option value="">Assign a user…</option>
              {users.filter((u) => !assignedUsers.has(u.id)).map((u) => <option key={u.id} value={u.id}>{u.first_name} {u.last_name} ({u.email})</option>)}
            </select>
            <Button size="sm" disabled={!pickUser} onClick={() => run(async () => { await http(`/admin/applications/${id}/assignments`, { method: "POST", body: { user_id: Number(pickUser) } }); setPickUser(""); }, "User assigned")}>Assign</Button>
            <select aria-label="Assign a group" className={`${fieldClass} w-64`} value={pickGroup} onChange={(e) => setPickGroup(e.target.value)}>
              <option value="">Assign a group…</option>
              {groups.filter((g) => !assignedGroups.has(g.id)).map((g) => <option key={g.id} value={g.id}>{g.name}</option>)}
            </select>
            <Button size="sm" disabled={!pickGroup} onClick={() => run(async () => { await http(`/admin/applications/${id}/assignments`, { method: "POST", body: { group_id: Number(pickGroup) } }); setPickGroup(""); }, "Group assigned")}>Assign</Button>
          </div>
          {assignments.length === 0 ? <p className="text-sm text-muted-foreground">Nobody is assigned yet.</p> : (
            <ul className="divide-y rounded-md border" data-testid="assignments">
              {assignments.map((a) => (
                <li key={a.id} className="flex items-center justify-between gap-2 px-4 py-2 text-sm">
                  <span><Badge tone="info">{a.type}</Badge> <span className="ml-2 font-medium">{a.name}</span> <span className="text-muted-foreground">{a.detail}</span></span>
                  <Button size="sm" variant="ghost" aria-label={`Remove ${a.name}`} onClick={() => run(() => http(`/admin/applications/${id}/assignments/${a.id}`, { method: "DELETE" }), "Assignment removed")}>Remove</Button>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
      </>)}
    </div>
  );
}
