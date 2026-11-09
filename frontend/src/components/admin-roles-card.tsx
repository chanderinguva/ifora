"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { http } from "@/lib/http";

type Role = { id: string; label: string; description: string };
type Source = { via: string; group_name?: string };

/** Super administrators only: administrator roles assigned to this admin directly. Roles also arrive through team groups (shown below). */
export function AdminRolesCard({ userId }: { userId: number }) {
  const [catalog, setCatalog] = useState<Role[]>([]);
  const [roles, setRoles] = useState<string[]>([]);
  const [sources, setSources] = useState<Record<string, Source[]>>({});
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  useEffect(() => {
    http<{ items: Role[] }>("/admin/roles").then((r) => setCatalog(r.items)).catch(() => {});
    http<{ roles: string[]; sources: Record<string, Source[]> }>(`/admin/roles/users/${userId}`).then((r) => { setRoles(r.roles); setSources(r.sources); }).catch((e) => setMsg({ ok: false, text: e.message }));
  }, [userId]);

  const toggle = (id: string) => setRoles((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id]));
  async function save() {
    setMsg(null);
    try {
      const r = await http<{ roles: string[] }>(`/admin/roles/users/${userId}`, { method: "PUT", body: { roles } });
      setRoles(r.roles); setMsg({ ok: true, text: "Roles saved; they apply on the administrator's next request" });
    } catch (e) { setMsg({ ok: false, text: e instanceof Error ? e.message : "Failed" }); }
  }

  return (
    <Card className="mb-6" data-testid="admin-roles">
      <CardHeader><CardTitle>Administrator roles</CardTitle></CardHeader>
      <CardContent className="space-y-3 text-sm">
        <p className="text-muted-foreground">Roles selected here are assigned to this person directly. With no role at all (directly or through a team group) an administrator cannot use any administrator function.</p>
        {Object.entries(sources).filter(([, s]) => s.some((x) => x.via === "group")).map(([role, s]) => (
          <p key={role} className="text-xs" data-testid={`role-via-${role}`}>
            <span className="font-medium">{catalog.find((c) => c.id === role)?.label ?? role}</span> also comes from {s.filter((x) => x.via === "group").map((x) => x.group_name).join(", ")}
          </p>
        ))}
        {msg && <Alert variant={msg.ok ? "default" : "destructive"} role="status"><AlertDescription>{msg.text}</AlertDescription></Alert>}
        {catalog.map((r) => (
          <label key={r.id} className="flex items-start gap-2">
            <input type="checkbox" className="mt-1" checked={roles.includes(r.id)} onChange={() => toggle(r.id)} data-testid={`role-${r.id}`} />
            <span><span className="font-medium">{r.label}</span><span className="block text-xs text-muted-foreground">{r.description}</span></span>
          </label>
        ))}
        <Button size="sm" onClick={save} data-testid="roles-save">Save roles</Button>
      </CardContent>
    </Card>
  );
}
