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
import { AttrField, fromApi, toApi } from "@/components/attr-field";
import { USER_STATUSES, statusTone, type ProfileAttribute, type User } from "@/lib/types";


export default function UserDetail() {
  const { id } = useParams<{ id: string }>();
  const me = useCurrentUser();
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [issuedCode, setIssuedCode] = useState<string | null>(null);
  const [form, setForm] = useState({ first_name: "", last_name: "", email: "" });
  const [schema, setSchema] = useState<ProfileAttribute[]>([]);
  const [attrs, setAttrs] = useState<Record<string, string>>({});
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [newPw, setNewPw] = useState("");

  const apply = useCallback((u: User) => {
    setUser(u);
    setForm({ first_name: u.first_name, last_name: u.last_name, email: u.email });
    setAttrs(Object.fromEntries(Object.entries(u.profile_attributes ?? {}).map(([k, v]) => [k, fromApi(v)])));
  }, []);

  useEffect(() => {
    http<{ items: ProfileAttribute[] }>("/admin/profile-attributes").then((r) => setSchema(r.items)).catch(() => {});
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
      const profile_attributes: Record<string, string | number | boolean> = {};
      for (const a of schema) {
        const v = toApi(a, attrs[a.key] ?? "");
        if (v !== null) profile_attributes[a.key] = v;
      }
      apply(await http<User>(`/admin/users/${id}`, { method: "PATCH", body: { ...form, profile_attributes } }));
    }, "Saved");

  return (
    <div className="max-w-3xl">
      <PageHeader title={`${user.first_name} ${user.last_name}`}>
        <Link href="/admin/users" className="text-sm underline-offset-4 hover:underline">← All users</Link>
      </PageHeader>
      <div className="mb-4 flex flex-wrap gap-2 text-sm">
        <Badge tone={statusTone(user.status)}>{user.status.replace("_", " ")}</Badge>
        {user.mfa_enabled && <Badge tone="good">MFA</Badge>}
        {(user.passkey_count ?? 0) > 0 && <Badge tone="good">{user.passkey_count} passkey{user.passkey_count === 1 ? "" : "s"}</Badge>}
        {user.passkey_required && <Badge tone="info">passkey required</Badge>}
        {user.is_super_admin ? <Badge tone="info">Super admin</Badge> : user.is_admin ? <Badge tone="info">Admin</Badge> : <Badge>User</Badge>}
        <span className="text-muted-foreground">Created {fmt(user.created_at)} · Last login {fmt(user.last_login_at)}</span>
      </div>

      {msg && (
        <Alert variant={msg.ok ? "default" : "destructive"} className="mb-4" role="status">
          <AlertDescription>{msg.text}</AlertDescription>
        </Alert>
      )}
      {issuedCode && (
        <Alert className="mb-4" data-testid="issued-code">
          <AlertDescription>
            Enrolment code: <code className="font-mono text-base font-semibold">{issuedCode}</code>
          </AlertDescription>
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
        <CardContent className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            {schema.map((a) => (
              <div key={a.key} className="space-y-2">
                <Label htmlFor={`attr-${a.key}`}>{a.display_name}{a.user_editable ? "" : <span className="ml-1 text-xs text-muted-foreground">(admin only)</span>}</Label>
                <AttrField attr={a} value={attrs[a.key] ?? ""} onChange={(v) => setAttrs({ ...attrs, [a.key]: v })} />
              </div>
            ))}
          </div>
          <p className="text-xs text-muted-foreground">Attributes are defined in the <Link className="underline underline-offset-4" href="/admin/profile-editor">Profile editor</Link>.</p>
        </CardContent>
      </Card>

      <div className="mb-8 flex flex-wrap gap-3">
        <Button onClick={save} disabled={protectedTarget && !isSelf}>Save changes</Button>
        {!isSelf && !user.is_super_admin && (
          <Button
            variant="outline"
            disabled={protectedTarget}
            onClick={() =>
              run(async () => apply(await http<User>(`/admin/users/${id}`, { method: "PATCH", body: { status: user.status === "active" ? "deprovisioned" : "active" } })),
                user.status === "active" ? "User deactivated; sessions ended and removed from all groups" : "User activated")
            }
          >
            {user.status === "active" ? "Deactivate" : "Activate"}
          </Button>
        )}
        {!isSelf && !user.is_super_admin && (
          <select
            aria-label="Set account status"
            className="h-10 rounded-md border bg-background px-3 text-sm"
            value={user.status}
            disabled={protectedTarget}
            onChange={(e) => {
              const next = e.target.value;
              if (next === "deprovisioned" && !confirm("Deactivate this user? They are signed out everywhere and removed from every group.")) return;
              run(async () => apply(await http<User>(`/admin/users/${id}`, { method: "PATCH", body: { status: next } })), `Status set to ${next.replace("_", " ")}`);
            }}
          >
            {USER_STATUSES.map((s) => <option key={s.value} value={s.value} title={s.hint}>{s.label}</option>)}
          </select>
        )}
        {(user.mfa_enabled || (user.passkey_count ?? 0) > 0 || user.passkey_required) && !isSelf && !protectedTarget && (
          <Button
            variant="outline"
            onClick={() => {
              if (!confirm("Remove this user's authenticator app, passkeys and passkey requirement? They will be signed out everywhere and can sign in with their password again.")) return;
              run(async () => {
                await http(`/admin/users/${id}/mfa/reset`, { method: "POST" });
                apply(await http<User>(`/admin/users/${id}`));
              }, "Sign-in factors reset; the user's sessions were ended");
            }}
          >
            Reset MFA &amp; passkeys
          </Button>
        )}
        {me.is_super_admin && user.is_admin && !user.is_super_admin && user.mfa_setup_required && (
          <Button
            variant="outline"
            onClick={() =>
              run(async () => {
                const r = await http<{ code: string; expires_in_hours: number }>(`/admin/users/${id}/enrollment-code`, { method: "POST" });
                setIssuedCode(`${r.code} (single use, valid ${r.expires_in_hours}h)`);
              }, "Enrolment code issued. Give it to the administrator out of band; it is shown only once.")
            }
          >
            Issue enrolment code
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
