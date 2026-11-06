"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge, PageHeader, fieldClass, td, th } from "@/components/bits";
import { http, qs, type Page } from "@/lib/http";
import type { Group, User } from "@/lib/types";

export default function GroupDetail() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [group, setGroup] = useState<Group | null>(null);
  const [form, setForm] = useState({ name: "", description: "" });
  const [candidates, setCandidates] = useState<User[]>([]);
  const [pick, setPick] = useState("");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const apply = useCallback((g: Group) => {
    setGroup(g);
    setForm({ name: g.name, description: g.description ?? "" });
  }, []);

  useEffect(() => {
    http<Group>(`/admin/groups/${id}`).then(apply).catch((e) => setMsg({ ok: false, text: e.message }));
    http<Page<User>>(`/admin/users${qs({ page_size: 100, status: "active" })}`).then((p) => setCandidates(p.items)).catch(() => {});
  }, [id, apply]);

  async function run(fn: () => Promise<unknown>, ok: string) {
    setMsg(null);
    try {
      await fn();
      setMsg({ ok: true, text: ok });
    } catch (e) {
      setMsg({ ok: false, text: e instanceof Error ? e.message : "Failed" });
    }
  }

  if (!group) return <div className="text-sm text-muted-foreground">{msg ? msg.text : "Loading…"}</div>;

  const memberIds = new Set((group.members ?? []).map((m) => m.id));
  const available = candidates.filter((u) => !memberIds.has(u.id));

  return (
    <div className="max-w-3xl">
      <PageHeader title={group.name}>
        <Link href="/admin/groups" className="text-sm underline-offset-4 hover:underline">← All groups</Link>
      </PageHeader>
      {group.is_system_group && <div className="mb-4"><Badge>system group (read-only)</Badge></div>}
      {msg && (
        <Alert variant={msg.ok ? "default" : "destructive"} className="mb-4" role="status"><AlertDescription>{msg.text}</AlertDescription></Alert>
      )}

      <Card className="mb-6">
        <CardHeader><CardTitle>Details</CardTitle></CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="gname">Name</Label>
            <Input id="gname" disabled={group.is_system_group} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          </div>
          <div className="space-y-2">
            <Label htmlFor="gdesc">Description</Label>
            <Input id="gdesc" disabled={group.is_system_group} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
          </div>
          <Button disabled={group.is_system_group} onClick={() => run(async () => apply(await http<Group>(`/admin/groups/${id}`, { method: "PATCH", body: form })), "Saved")}>
            Save changes
          </Button>
        </CardContent>
      </Card>

      <Card className="mb-6">
        <CardHeader><CardTitle>Members ({group.members?.length ?? 0})</CardTitle></CardHeader>
        <CardContent className="space-y-4">
          <div className="flex gap-2">
            <select aria-label="User to add" className={fieldClass} value={pick} onChange={(e) => setPick(e.target.value)}>
              <option value="">Select a user to add…</option>
              {available.map((u) => (
                <option key={u.id} value={u.id}>{u.first_name} {u.last_name} ({u.email})</option>
              ))}
            </select>
            <Button disabled={!pick} onClick={() => run(async () => { apply(await http<Group>(`/admin/groups/${id}/members`, { method: "POST", body: { user_id: Number(pick) } })); setPick(""); }, "Member added")}>
              Add
            </Button>
          </div>
          <table className="w-full" data-testid="members-table">
            <thead className="border-b"><tr><th className={th}>Name</th><th className={th}>Email</th><th className={th}></th></tr></thead>
            <tbody>
              {group.members?.map((m) => (
                <tr key={m.id} className="border-b last:border-0">
                  <td className={td}>{m.first_name} {m.last_name}</td>
                  <td className={td}>{m.email}</td>
                  <td className={td + " text-right"}>
                    <Button size="sm" variant="outline" onClick={() => run(async () => apply(await http<Group>(`/admin/groups/${id}/members/${m.id}`, { method: "DELETE" })), "Member removed")}>
                      Remove
                    </Button>
                  </td>
                </tr>
              ))}
              {group.members?.length === 0 && <tr><td className={td} colSpan={3}>No members yet.</td></tr>}
            </tbody>
          </table>
        </CardContent>
      </Card>

      {!group.is_system_group && (
        <Card className="border-destructive/50">
          <CardHeader><CardTitle>Danger zone</CardTitle></CardHeader>
          <CardContent>
            <Button
              variant="destructive"
              onClick={async () => {
                if (!confirm(`Delete group "${group.name}"? Members are not deleted.`)) return;
                try {
                  await http(`/admin/groups/${id}`, { method: "DELETE" });
                  router.replace("/admin/groups");
                } catch (e) {
                  setMsg({ ok: false, text: e instanceof Error ? e.message : "Failed" });
                }
              }}
            >
              Delete group
            </Button>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
