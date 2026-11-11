"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge, PageHeader, fieldClass, fmt, td, th } from "@/components/bits";
import { useCurrentUser } from "@/components/auth-guard";
import { http, qs, type Page } from "@/lib/http";
import { useDirty } from "@/lib/use-dirty";
import { SaveButton } from "@/components/save-button";
import { toBody, type ProvApp, type ProvOptions } from "@/lib/provisioning";
import type { Group, User } from "@/lib/types";

type Assignment = { id: number; type: "user" | "group"; subject_id: number; name: string; detail: string };
type Link_ = { id: number; type: string; label: string; remote_id: string; state: string; last_error: string | null; last_synced_at: string | null };
type Task = { id: number; resource_type: string; user_id: number | null; group_id: number | null; op: string; status: string; attempts: number; result: string | null; last_error: string | null; created_at: string };

const stateTone = (s: string) => (s === "synced" || s === "succeeded" ? "good" : s === "error" || s === "failed" ? "bad" : "neutral");

export default function AppDetail() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const me = useCurrentUser();
  const [app, setApp] = useState<ProvApp | null>(null);
  const [canWriteApps, setCanWriteApps] = useState(false);
  useEffect(() => { http<{ access: Record<string, string> }>("/me/admin-access").then((r) => setCanWriteApps(r.access.applications === "write")).catch(() => {}); }, []);
  const canEdit = me.is_super_admin || canWriteApps;   // the applications area, as in Okta: org and app admins change apps, the rest view
  const [form, setForm] = useState({ name: "", description: "", base_url: "", auth_type: "bearer", header_name: "", secret: "", client_id: "", token_url: "", scope: "", rest: "" });
  const [opts, setOpts] = useState<ProvOptions | null>(null);
  const [rules, setRules] = useState<{ target: string; source: string }[]>([]);
  const [defaults, setDefaults] = useState<{ target: string; source: string }[]>([]);
  const [sources, setSources] = useState<string[]>([]);
  const [assignments, setAssignments] = useState<Assignment[]>([]);
  const [users, setUsers] = useState<User[]>([]);
  const [groups, setGroups] = useState<Group[]>([]);
  const [pickUser, setPickUser] = useState("");
  const [pickGroup, setPickGroup] = useState("");
  const [links, setLinks] = useState<Link_[]>([]);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [previewUser, setPreviewUser] = useState("");
  const [preview, setPreview] = useState<unknown>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const conn = useDirty({ form, opts }, app !== null);   // the connection settings and the attribute mapping are saved by separate buttons
  const map = useDirty(rules, app !== null);
  const { markClean: cleanConn } = conn;
  const { markClean: cleanMap } = map;
  const apply = useCallback((a: ProvApp) => {
    cleanConn(); cleanMap();
    setApp(a);
    setForm({ name: a.name, description: a.description ?? "", base_url: a.base_url, auth_type: a.auth_type, header_name: a.header_name ?? "", secret: "", client_id: a.client_id ?? "", token_url: a.token_url ?? "", scope: a.scope ?? "", rest: a.rest_config ? JSON.stringify(a.rest_config, null, 2) : "" });
    setOpts(a.options);
    setRules(a.mapping);
  }, [cleanConn, cleanMap]);

  // queued work finishes in the background, so these two lists are polled; the forms are not (a poll must never overwrite what is being typed)
  const refreshWork = useCallback(() => {
    http<{ Resources: Link_[] }>(`/admin/provisioning-apps/${id}/links?count=50`).then((r) => setLinks(r.Resources)).catch(() => {});
    http<{ items: Task[] }>(`/admin/provisioning-apps/${id}/tasks`).then((r) => setTasks(r.items)).catch(() => {});
  }, [id]);
  const refresh = useCallback(() => {
    http<ProvApp>(`/admin/provisioning-apps/${id}`).then(apply).catch((e) => setMsg({ ok: false, text: e.message }));
    http<{ items: Assignment[] }>(`/admin/provisioning-apps/${id}/assignments`).then((r) => setAssignments(r.items)).catch(() => {});
    refreshWork();
  }, [id, apply, refreshWork]);

  useEffect(() => {
    refresh();
    http<{ defaults: { target: string; source: string }[]; sources: string[] }>("/admin/provisioning-apps/mapping").then((r) => { setDefaults(r.defaults); setSources(r.sources); }).catch(() => {});
    http<Page<User>>(`/admin/users${qs({ count: 100, status: "active" })}`).then((p) => setUsers(p.Resources)).catch(() => {});
    http<Page<Group>>(`/admin/groups${qs({ count: 100 })}`).then((p) => setGroups(p.Resources)).catch(() => {});
    const t = setInterval(refreshWork, 10000);
    return () => clearInterval(t);
  }, [refresh, refreshWork]);

  async function run(fn: () => Promise<unknown>, ok?: string) {
    setMsg(null);
    try {
      await fn();
      if (ok) setMsg({ ok: true, text: ok });
      refresh();
    } catch (e) {
      setMsg({ ok: false, text: e instanceof Error ? e.message : "Failed" });
    }
  }

  if (!app || !opts) return <div className="text-sm text-muted-foreground">{msg ? msg.text : "Loading…"}</div>;

  const save = (over: Record<string, unknown> = {}) => {
    let rest_config: unknown = app.rest_config;
    if (app.kind === "rest") {
      try { rest_config = JSON.parse(form.rest); } catch { throw new Error("The gateway operations are not valid JSON"); }
    }
    return http<ProvApp>(`/admin/provisioning-apps/${id}`, { method: "PUT", body: {
      ...toBody(app), name: form.name, description: form.description || null, base_url: form.base_url, auth_type: form.auth_type,
      header_name: form.auth_type === "header" ? form.header_name : null,
      ...(form.auth_type === "oauth2" ? { client_id: form.client_id, token_url: form.token_url, scope: form.scope || null } : { client_id: null, token_url: null, scope: null }), options: opts, mapping: rules.filter((r) => r.target && r.source),
      rest_config, ...(form.secret ? { secret: form.secret } : {}), ...over,
    } });
  };

  const assignedUsers = new Set(assignments.filter((a) => a.type === "user").map((a) => a.subject_id));
  const assignedGroups = new Set(assignments.filter((a) => a.type === "group").map((a) => a.subject_id));
  const set = <K extends keyof ProvOptions>(k: K, v: ProvOptions[K]) => setOpts({ ...opts, [k]: v });

  return (
    <div className="max-w-4xl">
      <PageHeader title={app.name}>
        <Link href="/admin/app-provisioning" className="text-sm underline-offset-4 hover:underline">← All applications</Link>
      </PageHeader>
      {msg && <Alert variant={msg.ok ? "default" : "destructive"} className="mb-4" role="status"><AlertDescription>{msg.text}</AlertDescription></Alert>}

      <Card className="mb-6">
        <CardContent className="flex flex-wrap items-center gap-3 pt-6">
          <Badge tone={app.enabled ? "good" : "neutral"}>{app.enabled ? "provisioning on" : "provisioning off"}</Badge>
          <span className="text-sm text-muted-foreground">{app.kind === "scim" ? "SCIM 2.0" : "REST gateway"} · {app.provisioned} provisioned · {app.queued} queued{app.failed_tasks ? ` · ${app.failed_tasks} failed` : ""}</span>
          <span className="text-sm" data-testid="last-test">
            {app.last_test.ok === null ? "Not tested yet" : <>Last test: <Badge tone={app.last_test.ok ? "good" : "bad"}>{app.last_test.ok ? "ok" : "failed"}</Badge> {app.last_test.message}</>}
          </span>
          {canEdit && (
            <div className="ml-auto flex flex-wrap gap-2">
              <Button variant="outline" size="sm" data-testid="test-app" onClick={() => run(async () => { const r = await http<{ ok: boolean; message: string }>(`/admin/provisioning-apps/${id}/test`, { method: "POST" }); setMsg({ ok: r.ok, text: r.message }); })}>Test connection</Button>
              {app.enabled
                ? <Button variant="outline" size="sm" onClick={() => run(async () => { apply(await save({ enabled: false })); }, "Provisioning turned off")}>Turn off</Button>
                : <Button size="sm" data-testid="enable-app" disabled={app.last_test.ok !== true} title={app.last_test.ok !== true ? "Test the connection first" : ""} onClick={() => run(async () => { apply(await save({ enabled: true })); }, "Provisioning turned on")}>Turn on</Button>}
              {app.enabled && <Button variant="outline" size="sm" onClick={() => run(async () => { const r = await http<{ queued: { users: number; groups: number } }>(`/admin/provisioning-apps/${id}/sync`, { method: "POST" }); setMsg({ ok: true, text: `Queued ${r.queued.users} users and ${r.queued.groups} groups` }); })}>Sync now</Button>}
              {app.enabled && app.provisioned > 0 && <Button variant="outline" size="sm" data-testid="deprovision-all" onClick={() => { if (confirm(`Remove every assignment and ${opts.deactivate === "delete" ? "delete" : "deactivate"} all ${app.provisioned} accounts in ${app.name}?`)) run(async () => { const r = await http<{ assignments_removed: number }>(`/admin/provisioning-apps/${id}/deprovision-all`, { method: "POST" }); setMsg({ ok: true, text: `Removed ${r.assignments_removed} assignments; accounts are being deprovisioned` }); }); }}>Deprovision everyone</Button>}
              <Button variant="destructive" size="sm" onClick={() => { if (confirm(`Delete ${app.name}? Accounts already created in the application stay as they are.`)) run(async () => { await http(`/admin/provisioning-apps/${id}`, { method: "DELETE" }); router.push("/admin/app-provisioning"); }); }}>Delete</Button>
            </div>
          )}
        </CardContent>
      </Card>

      <Card className="mb-6">
        <CardHeader><CardTitle>Assignments</CardTitle></CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm text-muted-foreground">Users assigned here, and every active member of an assigned group, get an account. When someone is no longer assigned, or is not active, the account is {opts.deactivate === "delete" ? "deleted" : opts.deactivate === "patch" ? "deactivated" : "left alone"}.</p>
          <div className="flex flex-wrap gap-2">
            <select aria-label="Assign a user" className={`${fieldClass} w-64`} value={pickUser} onChange={(e) => setPickUser(e.target.value)}>
              <option value="">Assign a user…</option>
              {users.filter((u) => !assignedUsers.has(u.id)).map((u) => <option key={u.id} value={u.id}>{u.first_name} {u.last_name} ({u.email})</option>)}
            </select>
            <Button size="sm" disabled={!pickUser} onClick={() => run(async () => { await http(`/admin/provisioning-apps/${id}/assignments`, { method: "POST", body: { user_id: Number(pickUser) } }); setPickUser(""); }, "User assigned")}>Assign</Button>
            <select aria-label="Assign a group" className={`${fieldClass} w-64`} value={pickGroup} onChange={(e) => setPickGroup(e.target.value)}>
              <option value="">Assign a group…</option>
              {groups.filter((g) => !assignedGroups.has(g.id)).map((g) => <option key={g.id} value={g.id}>{g.name}</option>)}
            </select>
            <Button size="sm" disabled={!pickGroup} onClick={() => run(async () => { await http(`/admin/provisioning-apps/${id}/assignments`, { method: "POST", body: { group_id: Number(pickGroup) } }); setPickGroup(""); }, "Group assigned")}>Assign</Button>
          </div>
          {assignments.length === 0 ? <p className="text-sm text-muted-foreground">Nobody is assigned yet.</p> : (
            <ul className="divide-y rounded-md border" data-testid="assignments">
              {assignments.map((a) => (
                <li key={a.id} className="flex items-center justify-between gap-2 px-4 py-2 text-sm">
                  <span><Badge tone="info">{a.type}</Badge> <span className="ml-2 font-medium">{a.name}</span> <span className="text-muted-foreground">{a.detail}</span></span>
                  <Button size="sm" variant="ghost" aria-label={`Remove ${a.name}`} onClick={() => run(() => http(`/admin/provisioning-apps/${id}/assignments/${a.id}`, { method: "DELETE" }), "Assignment removed")}>Remove</Button>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      <Card className="mb-6">
        <CardHeader><CardTitle>Provisioned accounts</CardTitle></CardHeader>
        <CardContent>
          {links.length === 0 ? <p className="text-sm text-muted-foreground">Nothing provisioned yet.</p> : (
            <div className="overflow-x-auto rounded-md border"><table className="w-full" data-testid="links">
              <thead><tr><th className={th}>Account</th><th className={th}>Remote id</th><th className={th}>State</th><th className={th}>Last synced</th></tr></thead>
              <tbody>{links.map((l) => (
                <tr key={l.id} className="border-t"><td className={td}>{l.label} <span className="text-xs text-muted-foreground">{l.type}</span></td><td className={`${td} font-mono text-xs`}>{l.remote_id}</td>
                  <td className={td}><Badge tone={stateTone(l.state)}>{l.state}</Badge>{l.last_error && <div className="mt-1 text-xs text-bad">{l.last_error}</div>}</td><td className={td}>{fmt(l.last_synced_at)}</td></tr>))}
              </tbody></table></div>
          )}
        </CardContent>
      </Card>

      <Card className="mb-6">
        <CardHeader><CardTitle>Activity</CardTitle></CardHeader>
        <CardContent>
          {tasks.length === 0 ? <p className="text-sm text-muted-foreground">No activity yet.</p> : (
            <div className="overflow-x-auto rounded-md border"><table className="w-full" data-testid="tasks">
              <thead><tr><th className={th}>When</th><th className={th}>What</th><th className={th}>Status</th><th className={th}>Result</th><th className={th}></th></tr></thead>
              <tbody>{tasks.slice(0, 30).map((t) => (
                <tr key={t.id} className="border-t"><td className={td}>{fmt(t.created_at)}</td>
                  <td className={td}>{t.op === "delete_remote" ? "remove" : "sync"} {t.resource_type} #{t.user_id ?? t.group_id}</td>
                  <td className={td}><Badge tone={stateTone(t.status)}>{t.status}</Badge>{t.attempts > 1 && <span className="ml-2 text-xs text-muted-foreground">{t.attempts} attempts</span>}{t.last_error && <div className="mt-1 text-xs text-bad">{t.last_error}</div>}</td>
                  <td className={td}>{t.result ?? "—"}</td>
                  <td className={td}>{canEdit && t.status === "failed" && <Button size="sm" variant="outline" onClick={() => run(() => http(`/admin/provisioning-apps/${id}/tasks/${t.id}/retry`, { method: "POST" }), "Retry queued")}>Retry</Button>}</td></tr>))}
              </tbody></table></div>
          )}
        </CardContent>
      </Card>

      <Card className="mb-6">
        <CardHeader><CardTitle>Attribute mapping</CardTitle></CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm text-muted-foreground">The defaults below follow the SCIM core and enterprise schemas. Add rules to send something else; a rule for the same target replaces the default. A source is an attribute, or a template such as <code>{"{{first_name}} {{last_name}}"}</code>.</p>
          <details className="text-sm"><summary className="cursor-pointer text-muted-foreground">Default rules ({defaults.length})</summary>
            <ul className="mt-2 space-y-1 font-mono text-xs">{defaults.map((d) => <li key={d.target}>{d.target.replace("urn:ietf:params:scim:schemas:extension:enterprise:2.0:User", "enterprise")} ← {d.source}</li>)}</ul></details>
          <div className="space-y-2" data-testid="mapping-rules">
            {rules.map((r, i) => (
              <div key={i} className="flex flex-wrap items-center gap-2">
                <Input aria-label="Target attribute" className="w-64" placeholder="title or name.formatted" disabled={!canEdit} value={r.target} onChange={(e) => setRules(rules.map((x, j) => (j === i ? { ...x, target: e.target.value } : x)))} />
                <span>←</span>
                <Input aria-label="Source" list="prov-sources" className="w-64" placeholder="attribute or {{template}}" disabled={!canEdit} value={r.source} onChange={(e) => setRules(rules.map((x, j) => (j === i ? { ...x, source: e.target.value } : x)))} />
                {canEdit && <Button size="sm" variant="ghost" aria-label="Remove rule" onClick={() => setRules(rules.filter((_, j) => j !== i))}>Remove</Button>}
              </div>
            ))}
            <datalist id="prov-sources">{sources.map((s) => <option key={s} value={s} />)}</datalist>
            {canEdit && (
              <div className="flex gap-2">
                <Button size="sm" variant="outline" onClick={() => setRules([...rules, { target: "", source: "" }])}>Add rule</Button>
                <SaveButton dirty={map.dirty} size="sm" data-testid="save-mapping" onClick={() => run(async () => { apply(await save()); }, "Mapping saved")}>Save mapping</SaveButton>
              </div>
            )}
          </div>
          <div className="flex flex-wrap items-center gap-2 border-t pt-4">
            <select aria-label="Preview for user" className={`${fieldClass} w-64`} value={previewUser} onChange={(e) => setPreviewUser(e.target.value)}>
              <option value="">Preview for a user…</option>
              {users.map((u) => <option key={u.id} value={u.id}>{u.email}</option>)}
            </select>
            <Button size="sm" variant="outline" disabled={!previewUser} onClick={() => run(async () => setPreview(await http(`/admin/provisioning-apps/${id}/preview?user_id=${previewUser}`)))}>Preview payload</Button>
          </div>
          {preview !== null && <pre className="max-h-72 overflow-auto rounded bg-muted p-3 text-xs" data-testid="preview">{JSON.stringify(preview, null, 2)}</pre>}
        </CardContent>
      </Card>

      <Card className="mb-6">
        <CardHeader><CardTitle>Connection and behaviour</CardTitle></CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2"><Label htmlFor="d-name">Name</Label><Input id="d-name" disabled={!canEdit} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></div>
            <div className="space-y-2"><Label htmlFor="d-url">Base URL</Label><Input id="d-url" disabled={!canEdit} value={form.base_url} onChange={(e) => setForm({ ...form, base_url: e.target.value })} /></div>
            <div className="space-y-2"><Label htmlFor="d-auth">Authentication</Label>
              <select id="d-auth" disabled={!canEdit} className={fieldClass} value={form.auth_type} onChange={(e) => setForm({ ...form, auth_type: e.target.value })}>
                <option value="bearer">Bearer token</option><option value="basic">Basic (user:password)</option><option value="header">Custom header</option><option value="oauth2">OAuth2 client credentials</option></select></div>
            {form.auth_type === "oauth2" && <>
              <div className="space-y-2"><Label htmlFor="d-cid">Client ID</Label><Input id="d-cid" disabled={!canEdit} value={form.client_id} onChange={(e) => setForm({ ...form, client_id: e.target.value })} /></div>
              <div className="space-y-2"><Label htmlFor="d-tok">Token URL</Label><Input id="d-tok" disabled={!canEdit} value={form.token_url} onChange={(e) => setForm({ ...form, token_url: e.target.value })} /></div>
              <div className="space-y-2"><Label htmlFor="d-scope">Scope</Label><Input id="d-scope" disabled={!canEdit} value={form.scope} onChange={(e) => setForm({ ...form, scope: e.target.value })} /></div></>}
            {form.auth_type === "header" && <div className="space-y-2"><Label htmlFor="d-hdr">Header name</Label><Input id="d-hdr" disabled={!canEdit} value={form.header_name} onChange={(e) => setForm({ ...form, header_name: e.target.value })} /></div>}
            <div className="space-y-2"><Label htmlFor="d-secret">{form.auth_type === "oauth2" ? "New client secret" : "New credential"} (leave blank to keep the current one)</Label><Input id="d-secret" type="password" autoComplete="off" disabled={!canEdit} value={form.secret} onChange={(e) => setForm({ ...form, secret: e.target.value })} /></div>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" disabled={!canEdit} checked={opts.push_new_users} onChange={(e) => set("push_new_users", e.target.checked)} /> Create users in the application</label>
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" disabled={!canEdit} checked={opts.push_updates} onChange={(e) => set("push_updates", e.target.checked)} /> Push profile updates</label>
            {app.kind === "scim" && <label className="flex items-center gap-2 text-sm"><input type="checkbox" disabled={!canEdit} checked={opts.push_groups} onChange={(e) => set("push_groups", e.target.checked)} /> Push assigned groups (SCIM Groups)</label>}
            <div className="space-y-1"><Label htmlFor="d-deact">When a user loses access</Label>
              <select id="d-deact" disabled={!canEdit} className={fieldClass} value={opts.deactivate} onChange={(e) => set("deactivate", e.target.value as ProvOptions["deactivate"])}>
                <option value="patch">Deactivate the account</option><option value="delete">Delete the account</option><option value="none">Do nothing</option></select></div>
            {app.kind === "scim" && <div className="space-y-1"><Label htmlFor="d-style">Updates use</Label>
              <select id="d-style" disabled={!canEdit} className={fieldClass} value={opts.update_style} onChange={(e) => set("update_style", e.target.value as ProvOptions["update_style"])}>
                <option value="put">PUT (replace)</option><option value="patch">PATCH</option></select></div>}
            <div className="space-y-1"><Label htmlFor="d-ident">userName is the user&apos;s</Label>
              <select id="d-ident" disabled={!canEdit} className={fieldClass} value={opts.user_identifier} onChange={(e) => set("user_identifier", e.target.value as ProvOptions["user_identifier"])}>
                <option value="email">Email</option><option value="username">Username</option></select></div>
          </div>
          {app.kind === "rest" && (
            <div className="space-y-2"><Label htmlFor="d-rest">Gateway operations (JSON)</Label>
              <textarea id="d-rest" rows={14} spellCheck={false} disabled={!canEdit} className={`${fieldClass} h-auto font-mono text-xs`} value={form.rest} onChange={(e) => setForm({ ...form, rest: e.target.value })} /></div>
          )}
          {canEdit ? <SaveButton dirty={conn.dirty} onClick={() => run(async () => { apply(await save()); }, "Saved")}>Save</SaveButton>
            : <p className="text-xs text-muted-foreground">Only super, organization and application administrators can change the connection.</p>}
        </CardContent>
      </Card>
    </div>
  );
}
