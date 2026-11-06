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
import type { User } from "@/lib/types";

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
          <option value="active">Active</option>
          <option value="inactive">Inactive</option>
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
                    <Badge tone={u.status === "active" ? "good" : "bad"}>{u.status}</Badge>
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

function CreateUser({ canMakeAdmin, onDone }: { canMakeAdmin: boolean; onDone: () => void }) {
  const [f, setF] = useState({ email: "", first_name: "", last_name: "", password: "", is_admin: false });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const set = (k: string, v: string | boolean) => setF((s) => ({ ...s, [k]: v }));

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await http("/admin/users", { method: "POST", body: f });
      onDone();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="mb-6">
      <CardHeader>
        <CardTitle>Create user</CardTitle>
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
            <Label htmlFor="nu-email">Email</Label>
            <Input id="nu-email" type="email" required value={f.email} onChange={(e) => set("email", e.target.value)} />
          </div>
          <div className="space-y-2">
            <Label htmlFor="nu-pw">Initial password</Label>
            <Input id="nu-pw" type="password" required autoComplete="new-password" value={f.password} onChange={(e) => set("password", e.target.value)} />
            <p className="text-xs text-muted-foreground">12+ characters, mixed case, with a digit.</p>
          </div>
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
