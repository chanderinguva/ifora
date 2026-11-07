"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge, PageHeader, Pager, fieldClass, fmt, td, th } from "@/components/bits";
import { useCurrentUser } from "@/components/auth-guard";
import { http, qs, type Page } from "@/lib/http";
import { AttrField, toApi } from "@/components/attr-field";
import { USER_STATUSES, statusTone, type Group, type ProfileAttribute, type User } from "@/lib/types";

const PAGE_SIZE = 15;

export default function UsersPage() {
  const me = useCurrentUser();
  const [data, setData] = useState<Page<User> | null>(null);
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  const load = useCallback(() => {
    http<Page<User>>(`/admin/users${qs({ q, status, page, page_size: PAGE_SIZE })}`)
      .then(setData)
      .catch((e) => setError(e.message));
  }, [q, status, page]);

  useEffect(() => {
    const t = setTimeout(load, 200);
    return () => clearTimeout(t);
  }, [load]);

  return (
    <div>
      <PageHeader title="Users">
        <Button onClick={() => setCreating((v) => !v)}>
          <Plus className="mr-1 h-4 w-4" /> New user
        </Button>
      </PageHeader>

      {creating && (
        <CreateUser
          canMakeAdmin={me.is_super_admin}
          onDone={() => {
            setCreating(false);
            load();
          }}
        />
      )}

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
      </div>

      {error && (
        <Alert variant="destructive" className="mb-4">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      <Card>
        <CardContent className="overflow-x-auto p-0">
          <table className="w-full" data-testid="users-table">
            <thead className="border-b">
              <tr>
                <th className={th}>Name</th>
                <th className={th}>Email</th>
                <th className={th}>Role</th>
                <th className={th}>Status</th>
                <th className={th}>Last login</th>
              </tr>
            </thead>
            <tbody>
              {data?.items.map((u) => (
                <tr key={u.id} className="border-b last:border-0 hover:bg-accent/30">
                  <td className={td}>
                    <Link className="font-medium underline-offset-4 hover:underline" href={`/admin/users/${u.id}`}>
                      {u.first_name} {u.last_name}
                    </Link>
                  </td>
                  <td className={td}>{u.email}</td>
                  <td className={td}>
                    {u.is_super_admin ? <Badge tone="info">Super admin</Badge> : u.is_admin ? <Badge tone="info">Admin</Badge> : <Badge>User</Badge>}
                  </td>
                  <td className={td}>
                    <Badge tone={statusTone(u.status)}>{u.status.replace("_", " ")}</Badge>
                  </td>
                  <td className={td}>{fmt(u.last_login_at)}</td>
                </tr>
              ))}
              {data && data.items.length === 0 && (
                <tr>
                  <td className={td} colSpan={5}>No users match.</td>
                </tr>
              )}
            </tbody>
          </table>
        </CardContent>
      </Card>
      {data && <Pager page={page} pageSize={PAGE_SIZE} total={data.total} onPage={setPage} />}
    </div>
  );
}

const FIELD_NOTE = "Attributes set here are managed by administrators; users cannot change them, so group rules may use them.";

function CreateUser({ canMakeAdmin, onDone }: { canMakeAdmin: boolean; onDone: () => void }) {
  const [f, setF] = useState({ email: "", first_name: "", last_name: "", username: "", password: "", is_admin: false });
  const [schema, setSchema] = useState<ProfileAttribute[]>([]);
  const [attrs, setAttrs] = useState<Record<string, string>>({});
  const [pwMode, setPwMode] = useState<"set" | "generate">("generate");
  const [groups, setGroups] = useState<Group[]>([]);
  const [picked, setPicked] = useState<number[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [created, setCreated] = useState<{ email: string; password: string } | null>(null);
  const set = (k: string, v: string | boolean) => setF((s) => ({ ...s, [k]: v }));

  useEffect(() => {
    http<{ items: ProfileAttribute[] }>("/admin/profile-attributes").then((r) => setSchema(r.items.filter((a) => !a.user_editable))).catch(() => {});
    http<Page<Group>>(`/admin/groups${qs({ page: 1, page_size: 100 })}`).then((r) => setGroups(r.items.filter((g) => !g.is_system_group))).catch(() => {});
  }, []);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const body: Record<string, unknown> = {
        email: f.email, first_name: f.first_name, last_name: f.last_name, is_admin: f.is_admin, group_ids: picked,
        profile_attributes: Object.fromEntries(schema.map((a) => [a.key, toApi(a, attrs[a.key] ?? "")]).filter(([, v]) => v !== null)),
      };
      if (f.username.trim()) body.username = f.username.trim();
      if (pwMode === "set") body.password = f.password;
      else body.generate_password = true;
      const r = await http<{ temporary_password?: string }>("/admin/users", { method: "POST", body });
      if (r.temporary_password) setCreated({ email: f.email, password: r.temporary_password });
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
            <Label htmlFor="nu-email">Primary email</Label>
            <Input id="nu-email" type="email" required value={f.email} onChange={(e) => set("email", e.target.value)} />
          </div>
          <div className="space-y-2">
            <Label htmlFor="nu-username">Username <span className="text-muted-foreground">(optional)</span></Label>
            <Input id="nu-username" placeholder="defaults to the part before @" value={f.username} onChange={(e) => set("username", e.target.value)} />
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
            {pwMode === "set" && (
              <div className="space-y-1">
                <Label htmlFor="nu-pw">Initial password</Label>
                <Input id="nu-pw" type="password" required autoComplete="new-password" value={f.password} onChange={(e) => set("password", e.target.value)} />
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
