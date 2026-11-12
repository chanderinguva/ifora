"use client";

import { Avatar } from "@/components/avatar";
import { PasswordRules } from "@/components/password-rules";
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge, PageHeader, Pager, fieldClass, fmt, mono, td, th, tr } from "@/components/bits";
import { useCurrentUser } from "@/components/auth-guard";
import { http, pageQs, qs, type Page } from "@/lib/http";
import { AttrField, toApi } from "@/components/attr-field";
import { ImportPanel, UserCsvButtons } from "@/components/user-csv";
import { UserLifecycle } from "@/components/user-lifecycle";
import { USER_STATUSES, statusTone, type Group, type ProfileAttribute, type User } from "@/lib/types";

const PAGE_SIZE = 15;
// the Role filter: account kind first, then the built-in administrator roles (held directly or through a group)
const ROLE_FILTERS: [string, string][] = [
  ["super_admin", "Super admin"], ["admin", "Any administrator"], ["user", "Not an administrator"],
  ["org_admin", "Organization administrator"], ["read_only_admin", "Read-only administrator"], ["help_desk_admin", "Help desk administrator"],
  ["app_admin", "Application administrator"], ["group_admin", "Group administrator"], ["report_admin", "Report administrator"],
];

export default function UsersPage() {
  const me = useCurrentUser();
  const [data, setData] = useState<Page<User> | null>(null);
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [role, setRole] = useState("");
  const [page, setPage] = useState(1);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [importing, setImporting] = useState(false);
  const [picked, setPicked] = useState<Set<number>>(new Set());
  const [note, setNote] = useState<string | null>(null);
  const toggle = (id: number) => setPicked((p) => { const n = new Set(p); if (n.has(id)) n.delete(id); else n.add(id); return n; });
  async function bulk(action: string) {
    setNote(null);
    try {
      const r = await http<{ done: number; results: { user_id: number; ok: boolean; reason?: string }[] }>("/admin/users/bulk", { method: "POST", body: { user_ids: [...picked], action } });
      const skipped = r.results.filter((x) => !x.ok);
      setNote(`${r.done} user${r.done === 1 ? "" : "s"} updated${skipped.length ? `; ${skipped.length} skipped (${[...new Set(skipped.map((x) => x.reason))].join("; ")})` : ""}`);
      setPicked(new Set());
      load();
    } catch (e) { setError(e instanceof Error ? e.message : "Failed"); }
  }

  const load = useCallback(() => {
    http<Page<User>>(`/admin/users${qs({ q, status, role, ...pageQs(page, PAGE_SIZE) })}`)
      .then(setData)
      .catch((e) => setError(e.message));
  }, [q, status, role, page]);

  useEffect(() => {
    const st = new URLSearchParams(window.location.search).get("status");
    if (st) setStatus(st);
  }, []);

  useEffect(() => {
    const t = setTimeout(load, 200);
    return () => clearTimeout(t);
  }, [load]);

  return (
    <div>
      <PageHeader title="Users">
        <UserCsvButtons q={q} status={status} onToggleImport={() => setImporting((v) => !v)} onError={(m) => setError(m)} />
        <Button onClick={() => setCreating((v) => !v)}>
          <Plus className="mr-1 h-4 w-4" /> New user
        </Button>
      </PageHeader>

      {importing && <ImportPanel onClose={() => setImporting(false)} onImported={load} onError={(m) => setError(m)} />}
      {creating && (
        <CreateUser
          canMakeAdmin={me.is_super_admin}
          onDone={() => {
            setCreating(false);
            load();
          }}
        />
      )}

      <UserLifecycle current={status} onPick={(s) => { setStatus(s); setPage(1); }} />

      <div className="mb-4 flex flex-wrap gap-3">
        <Input
          aria-label="Search users"
          placeholder="Search name, email or username"
          className="max-w-xs"
          value={q}
          onChange={(e) => {
            setQ(e.target.value);
            setPage(1);
          }}
        />
        <select
          aria-label="Filter by status"
          className={fieldClass + " max-w-[10rem]"}
          value={status}
          onChange={(e) => {
            setStatus(e.target.value);
            setPage(1);
          }}
        >
          <option value="">All statuses</option>
          {USER_STATUSES.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
        </select>
        <select
          aria-label="Filter by role"
          className={fieldClass + " max-w-[14rem]"}
          value={role}
          onChange={(e) => {
            setRole(e.target.value);
            setPage(1);
          }}
        >
          <option value="">All roles</option>
          {ROLE_FILTERS.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
        </select>
      </div>

      {error && (
        <Alert variant="destructive" className="mb-4">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {note && <Alert className="mb-4" role="status" data-testid="bulk-note"><AlertDescription>{note}</AlertDescription></Alert>}
      {picked.size > 0 && (
        <div className="mb-3 flex flex-wrap items-center gap-2 rounded-lg border bg-selected p-2 text-sm" data-testid="bulk-bar">
          <span className="px-2 font-medium text-selected-foreground tabular-nums">{picked.size} selected</span>
          {([["activate", "Activate"], ["suspend", "Suspend"], ["unsuspend", "Unsuspend"], ["unlock", "Unlock"], ["deactivate", "Deactivate"]] as const).map(([a, l]) => (
            <Button key={a} size="sm" variant={a === "deactivate" ? "destructive" : "outline"} data-testid={`bulk-${a}`}
              onClick={() => { if (a !== "deactivate" || confirm(`Deactivate ${picked.size} user(s)? Sessions end and they are removed from all groups.`)) bulk(a); }}>{l}</Button>
          ))}
          <Button size="sm" variant="ghost" onClick={() => setPicked(new Set())}>Clear</Button>
        </div>
      )}

      <Card>
        <CardContent className="overflow-x-auto p-0">
          <table className="w-full" data-testid="users-table">
            <thead className="border-b">
              <tr>
                <th className={th + " w-10"}><input type="checkbox" aria-label="Select all on this page" checked={!!data && data.Resources.length > 0 && data.Resources.every((u) => picked.has(u.id))}
                  onChange={(e) => setPicked(e.target.checked && data ? new Set(data.Resources.map((u) => u.id)) : new Set())} /></th>
                <th className={th}>Name</th>
                <th className={th}>Email</th>
                <th className={th}>Role</th>
                <th className={th}>Status</th>
                <th className={th}>Last login</th>
              </tr>
            </thead>
            <tbody>
              {data?.Resources.map((u) => (
                <tr key={u.id} className={tr} data-selected={picked.has(u.id)}>
                  <td className={td}><input type="checkbox" aria-label={`Select ${u.email}`} checked={picked.has(u.id)} onChange={() => toggle(u.id)} /></td>
                  <td className={td}>
                    <Link className="inline-flex items-center gap-2 font-medium underline-offset-4 hover:underline" href={`/admin/users/${u.id}`}>
                      <Avatar user={u} size={28} />
                      {u.first_name} {u.last_name}
                    </Link>
                  </td>
                  <td className={td + " font-mono text-[13px]"}>{u.email}</td>
                  <td className={td}>
                    {u.is_super_admin ? <Badge tone="info">Super admin</Badge> : u.is_admin ? <Badge tone="info">Admin</Badge> : <Badge>User</Badge>}
                  </td>
                  <td className={td}>
                    <Badge tone={statusTone(u.status)}>{u.status.replace("_", " ")}</Badge>
                  </td>
                  <td className={td + " " + mono}>{fmt(u.last_login_at)}</td>
                </tr>
              ))}
              {data && data.Resources.length === 0 && (
                <tr>
                  <td className={td} colSpan={6}>No users match.</td>
                </tr>
              )}
            </tbody>
          </table>
        </CardContent>
      </Card>
      {data && <Pager page={page} pageSize={PAGE_SIZE} total={data.totalResults} onPage={setPage} />}
    </div>
  );
}

const FIELD_NOTE = "Attributes set here are managed by administrators; users cannot change them, so group rules may use them.";

function CreateUser({ canMakeAdmin, onDone }: { canMakeAdmin: boolean; onDone: () => void }) {
  const [f, setF] = useState({ email: "", first_name: "", last_name: "", username: "", password: "", is_admin: false });
  const [schema, setSchema] = useState<ProfileAttribute[]>([]);
  const [attrs, setAttrs] = useState<Record<string, string>>({ user_type: "Employee" });
  const [pwMode, setPwMode] = useState<"set" | "generate" | "invite">("generate");
  const [groups, setGroups] = useState<Group[]>([]);
  const [picked, setPicked] = useState<number[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [created, setCreated] = useState<{ email: string; password: string } | null>(null);
  const [sugg, setSugg] = useState<{ username: string | null; email: string | null; email_domain: string | null }>({ username: null, email: null, email_domain: null });
  const set = (k: string, v: string | boolean) => setF((s) => ({ ...s, [k]: v }));

  // preview the username / email the new user would get (nothing is reserved until the account is created)
  useEffect(() => {
    const t = setTimeout(() => {
      http<typeof sugg>(`/admin/users/suggest-identity${qs({ first_name: f.first_name, last_name: f.last_name })}`).then(setSugg).catch(() => {});
    }, 250);
    return () => clearTimeout(t);
  }, [f.first_name, f.last_name]);

  useEffect(() => {
    http<{ items: ProfileAttribute[] }>("/admin/profile-attributes").then((r) => setSchema(r.items.filter((a) => !a.user_editable))).catch(() => {});
    http<Page<Group>>(`/admin/groups${qs({ count: 100 })}`).then((r) => setGroups(r.Resources.filter((g) => !g.is_system_group))).catch(() => {});
  }, []);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const body: Record<string, unknown> = {
        first_name: f.first_name, last_name: f.last_name, is_admin: f.is_admin, group_ids: picked,
        profile_attributes: Object.fromEntries(schema.map((a) => [a.key, toApi(a, attrs[a.key] ?? "")]).filter(([, v]) => v !== null)),
      };
      if (f.email.trim()) body.email = f.email.trim();
      if (f.username.trim()) body.username = f.username.trim();
      if (pwMode === "set") body.password = f.password;
      else if (pwMode === "invite") body.send_invite = true;
      else body.generate_password = true;
      const r = await http<{ temporary_password?: string; invitation_sent?: boolean; access_allowlist?: string; email: string }>("/admin/users", { method: "POST", body });
      if (r.temporary_password) setCreated({ email: r.email, password: r.temporary_password }); // never hide a generated password
      else if (r.access_allowlist === "failed") setError("The user was created, but they could not be added to the demo invite list, so they will not get past the sign-in gate. Add them in Cloudflare Access, then retry the invitation.");
      else if (r.invitation_sent === false) setError("The user was created, but the invitation email could not be sent. Use “Send invite” on their page to retry.");
      else onDone();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed");
    } finally {
      setBusy(false);
    }
  }

  if (created) {
    return (
      <Card className="mb-6" data-testid="created-user">
        <CardHeader><CardTitle>User created</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          <p className="text-sm">Give <strong>{created.email}</strong> this temporary password through a secure channel. It is shown only once.</p>
          <code className="block rounded bg-muted px-3 py-2 font-mono text-base" data-testid="temp-password">{created.password}</code>
          <div className="flex gap-2">
            <Button variant="outline" onClick={() => navigator.clipboard?.writeText(created.password)}>Copy</Button>
            <Button onClick={onDone}>Done</Button>
          </div>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="mb-6">
      <CardHeader>
        <CardTitle>Add person</CardTitle>
      </CardHeader>
      <CardContent>
        {error && (
          <Alert variant="destructive" className="mb-4">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}
        <form onSubmit={submit} className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-2">
            <Label htmlFor="nu-first">First name</Label>
            <Input id="nu-first" required value={f.first_name} onChange={(e) => set("first_name", e.target.value)} />
          </div>
          <div className="space-y-2">
            <Label htmlFor="nu-last">Last name</Label>
            <Input id="nu-last" required value={f.last_name} onChange={(e) => set("last_name", e.target.value)} />
          </div>
          <div className="space-y-2">
            <Label htmlFor="nu-email">Primary email {sugg.email_domain && <span className="text-muted-foreground">(optional)</span>}</Label>
            <Input id="nu-email" type="email" required={!sugg.email_domain} data-testid="nu-email" value={f.email} onChange={(e) => set("email", e.target.value)}
              placeholder={sugg.email ?? (sugg.email_domain ? `username@${sugg.email_domain}` : "name@example.com")} />
            {sugg.email_domain && !f.email && <p className="text-xs text-muted-foreground" data-testid="nu-email-hint">Built from the username: {sugg.email ?? `username@${sugg.email_domain}`}</p>}
          </div>
          <div className="space-y-2">
            <Label htmlFor="nu-username">Username <span className="text-muted-foreground">(optional)</span></Label>
            <Input id="nu-username" data-testid="nu-username" placeholder={sugg.username ?? "first.last"} value={f.username} onChange={(e) => set("username", e.target.value)} />
            <p className="text-xs text-muted-foreground">Set once, then it never changes, even if the name or email does. A number is added if the name is taken.</p>
          </div>

          <fieldset className="space-y-2 sm:col-span-2">
            <legend className="text-sm font-medium">Organisation</legend>
            <div className="grid gap-3 sm:grid-cols-3">
              {schema.map((a) => (
                <div key={a.key} className="space-y-1">
                  <Label htmlFor={`nu-${a.key}`}>{a.display_name}</Label>
                  <AttrField idPrefix="nu" attr={a} value={attrs[a.key] ?? ""} onChange={(v) => setAttrs({ ...attrs, [a.key]: v })} />
                </div>
              ))}
            </div>
            <p className="text-xs text-muted-foreground">{FIELD_NOTE}</p>
          </fieldset>

          <fieldset className="space-y-2 sm:col-span-2">
            <legend className="text-sm font-medium">Groups</legend>
            {groups.length === 0 ? (
              <p className="text-sm text-muted-foreground">No groups yet.</p>
            ) : (
              <div className="flex flex-wrap gap-3">
                {groups.map((g) => (
                  <label key={g.id} className="flex items-center gap-2 text-sm">
                    <input type="checkbox" checked={picked.includes(g.id)} onChange={(e) => setPicked(e.target.checked ? [...picked, g.id] : picked.filter((x) => x !== g.id))} />
                    {g.name}
                  </label>
                ))}
              </div>
            )}
            <p className="text-xs text-muted-foreground">Group rules may add more groups automatically based on the attributes above.</p>
          </fieldset>

          <fieldset className="space-y-2 sm:col-span-2">
            <legend className="text-sm font-medium">Password</legend>
            <label className="flex items-center gap-2 text-sm">
              <input type="radio" name="pwmode" checked={pwMode === "generate"} onChange={() => setPwMode("generate")} />
              Generate a random temporary password (shown once)
            </label>
            <label className="flex items-center gap-2 text-sm">
              <input type="radio" name="pwmode" checked={pwMode === "set"} onChange={() => setPwMode("set")} />
              I will set a password
            </label>
            <label className="flex items-center gap-2 text-sm">
              <input type="radio" name="pwmode" checked={pwMode === "invite"} onChange={() => setPwMode("invite")} />
              Email an invitation (the person chooses their own password; needs SMTP configured)
            </label>
            {pwMode === "set" && (
              <div className="space-y-1">
                <Label htmlFor="nu-pw">Initial password</Label>
                <Input id="nu-pw" type="password" required autoComplete="new-password" value={f.password} onChange={(e) => set("password", e.target.value)} />
                <PasswordRules />
                <p className="text-xs text-muted-foreground">12+ characters, mixed case, with a digit.</p>
              </div>
            )}
          </fieldset>

          {canMakeAdmin && (
            <label className="flex items-center gap-2 text-sm sm:col-span-2">
              <input type="checkbox" checked={f.is_admin} onChange={(e) => set("is_admin", e.target.checked)} />
              Grant administrator rights
            </label>
          )}
          <div className="sm:col-span-2">
            <Button type="submit" disabled={busy}>{busy ? "Creating…" : "Create user"}</Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}
