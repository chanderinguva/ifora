"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge, PageHeader, fmt } from "@/components/bits";
import { useCurrentUser } from "@/components/auth-guard";
import { http } from "@/lib/http";
import type { User } from "@/lib/types";

type Attr = { key: string; value: string };

export default function UserDetail() {
  const { id } = useParams<{ id: string }>();
  const me = useCurrentUser();
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [form, setForm] = useState({ first_name: "", last_name: "", email: "" });
  const [attrs, setAttrs] = useState<Attr[]>([]);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [newPw, setNewPw] = useState("");

  const apply = useCallback((u: User) => {
    setUser(u);
    setForm({ first_name: u.first_name, last_name: u.last_name, email: u.email });
    setAttrs(Object.entries(u.profile_attributes ?? {}).map(([key, v]) => ({ key, value: String(v ?? "") })));
  }, []);

  useEffect(() => {
    http<User>(`/admin/users/${id}`).then(apply).catch((e) => setMsg({ ok: false, text: e.message }));
  }, [id, apply]);

  async function run(fn: () => Promise<unknown>, okText: string) {
    setMsg(null);
    try {
      await fn();
      setMsg({ ok: true, text: okText });
    } catch (e) {
      setMsg({ ok: false, text: e instanceof Error ? e.message : "Failed" });
    }
  }

  if (!user) return <div className="text-sm text-muted-foreground">{msg ? msg.text : "Loading…"}</div>;

  const protectedTarget = user.is_super_admin || (user.is_admin && !me.is_super_admin);
  const isSelf = user.id === me.id;

  const resetPw = () =>
    run(async () => {
      await http(`/admin/users/${id}/password`, { method: "POST", body: { new_password: newPw } });
      setNewPw("");
    }, "Password reset; all of the user's sessions were ended");

  const save = () =>
    run(async () => {
      const profile_attributes: Record<string, string> = {};
      for (const a of attrs) if (a.key.trim()) profile_attributes[a.key.trim()] = a.value;
      apply(await http<User>(`/admin/users/${id}`, { method: "PATCH", body: { ...form, profile_attributes } }));
    }, "Saved");

  return (
    <div className="max-w-3xl">
      <PageHeader title={`${user.first_name} ${user.last_name}`}>
        <Link href="/admin/users" className="text-sm underline-offset-4 hover:underline">← All users</Link>
      </PageHeader>
      <div className="mb-4 flex flex-wrap gap-2 text-sm">
        <Badge tone={user.status === "active" ? "good" : "bad"}>{user.status}</Badge>
        {user.mfa_enabled && <Badge tone="good">MFA</Badge>}
        {user.is_super_admin ? <Badge tone="info">Super admin</Badge> : user.is_admin ? <Badge tone="info">Admin</Badge> : <Badge>User</Badge>}
        <span className="text-muted-foreground">Created {fmt(user.created_at)} · Last login {fmt(user.last_login_at)}</span>
      </div>

      {msg && (
        <Alert variant={msg.ok ? "default" : "destructive"} className="mb-4" role="status">
          <AlertDescription>{msg.text}</AlertDescription>
        </Alert>
      )}
      {protectedTarget && !isSelf && (
        <Alert className="mb-4">
          <AlertDescription>
            {user.is_super_admin ? "Super administrators cannot be modified by others." : "Only a super administrator can modify administrators."}
          </AlertDescription>
        </Alert>
      )}

      <Card className="mb-6">
        <CardHeader><CardTitle>Account</CardTitle></CardHeader>
        <CardContent className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-2">
            <Label htmlFor="first">First name</Label>
            <Input id="first" value={form.first_name} onChange={(e) => setForm({ ...form, first_name: e.target.value })} />
          </div>
          <div className="space-y-2">
            <Label htmlFor="last">Last name</Label>
            <Input id="last" value={form.last_name} onChange={(e) => setForm({ ...form, last_name: e.target.value })} />
          </div>
          <div className="space-y-2 sm:col-span-2">
            <Label htmlFor="email">Email</Label>
            <Input id="email" type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
          </div>
        </CardContent>
      </Card>

      <Card className="mb-6">
        <CardHeader><CardTitle>Profile attributes</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          {attrs.map((a, i) => (
            <div key={i} className="flex gap-2">
              <Input aria-label="Attribute name" placeholder="name (e.g. department)" value={a.key} onChange={(e) => setAttrs(attrs.map((x, j) => (j === i ? { ...x, key: e.target.value } : x)))} />
              <Input aria-label="Attribute value" placeholder="value" value={a.value} onChange={(e) => setAttrs(attrs.map((x, j) => (j === i ? { ...x, value: e.target.value } : x)))} />
              <Button type="button" variant="outline" onClick={() => setAttrs(attrs.filter((_, j) => j !== i))}>Remove</Button>
            </div>
          ))}
          <Button type="button" variant="secondary" onClick={() => setAttrs([...attrs, { key: "", value: "" }])}>Add attribute</Button>
          <p className="text-xs text-muted-foreground">Names: lowercase letters, digits and underscores. Up to 20 attributes.</p>
        </CardContent>
      </Card>

      <div className="mb-8 flex flex-wrap gap-3">
        <Button onClick={save} disabled={protectedTarget && !isSelf}>Save changes</Button>
        {!isSelf && !user.is_super_admin && (
          <Button
            variant="outline"
            disabled={protectedTarget}
            onClick={() =>
              run(async () => apply(await http<User>(`/admin/users/${id}`, { method: "PATCH", body: { status: user.status === "active" ? "inactive" : "active" } })),
                user.status === "active" ? "User deactivated; their sessions were ended" : "User activated")
            }
          >
            {user.status === "active" ? "Deactivate" : "Activate"}
          </Button>
        )}
        {user.mfa_enabled && !isSelf && !protectedTarget && (
          <Button
            variant="outline"
            onClick={() => {
              if (!confirm("Remove this user's two-step verification? They will be signed out everywhere.")) return;
              run(async () => {
                await http(`/admin/users/${id}/mfa/reset`, { method: "POST" });
                apply(await http<User>(`/admin/users/${id}`));
              }, "MFA removed; the user's sessions were ended");
            }}
          >
            Reset MFA
          </Button>
        )}
        {me.is_super_admin && !user.is_super_admin && (
          <Button
            variant="outline"
            onClick={() => run(async () => apply(await http<User>(`/admin/users/${id}`, { method: "PATCH", body: { is_admin: !user.is_admin } })), user.is_admin ? "Admin rights removed" : "Admin rights granted")}
          >
            {user.is_admin ? "Remove admin rights" : "Make administrator"}
          </Button>
        )}
      </div>

      <Card className="mb-6">
        <CardHeader><CardTitle>Groups</CardTitle></CardHeader>
        <CardContent>
          {user.groups && user.groups.length > 0 ? (
            <ul className="flex flex-wrap gap-2">
              {user.groups.map((g) => (
                <li key={g.id}><Link href={`/admin/groups/${g.id}`}><Badge tone="info">{g.name}</Badge></Link></li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-muted-foreground">Not a member of any group.</p>
          )}
        </CardContent>
      </Card>

      {!protectedTarget && (
        <Card className="mb-6">
          <CardHeader><CardTitle>Reset password</CardTitle></CardHeader>
          <CardContent>
            <form
              className="space-y-3"
              onSubmit={(e) => {
                e.preventDefault();
                resetPw();
              }}
            >
            <Label htmlFor="newpw">New password</Label>
            <Input id="newpw" type="password" autoComplete="new-password" value={newPw} onChange={(e) => setNewPw(e.target.value)} />
            <Button type="submit" variant="outline" disabled={!newPw}>
              Reset password
            </Button>
            </form>
          </CardContent>
        </Card>
      )}

      {!isSelf && !user.is_super_admin && !protectedTarget && (
        <Card className="border-destructive/50">
          <CardHeader><CardTitle>Danger zone</CardTitle></CardHeader>
          <CardContent>
            <Button
              variant="destructive"
              onClick={async () => {
                if (!confirm(`Permanently delete ${user.email}? This cannot be undone.`)) return;
                try {
                  await http(`/admin/users/${id}`, { method: "DELETE" });
                  router.replace("/admin/users");
                } catch (e) {
                  setMsg({ ok: false, text: e instanceof Error ? e.message : "Failed" });
                }
              }}
            >
              Delete user
            </Button>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
