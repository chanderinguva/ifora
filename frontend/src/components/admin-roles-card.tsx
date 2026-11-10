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

  // every role the person holds, in catalog order, with where it comes from (what is ticked below counts as direct even before it is saved)
  const effective = catalog
    .map((c) => ({ id: c.id, direct: roles.includes(c.id), groups: (sources[c.id] ?? []).filter((x) => x.via === "group").map((x) => x.group_name ?? "a group") }))
    .filter((r) => r.direct || r.groups.length > 0);

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
        <div data-testid="effective-roles">
          <div className="mb-1 font-medium">Effective roles</div>
          {effective.length === 0 ? (
            <p className="text-xs text-muted-foreground">None. This administrator cannot use any administrator function.</p>
          ) : (
            <ul className="space-y-0.5 text-xs">
              {effective.map(({ id, direct, groups }) => (
                <li key={id} data-testid={`role-via-${id}`}>
                  <span className="font-medium">{catalog.find((c) => c.id === id)?.label ?? id}</span>
                  {" "}<span className="text-muted-foreground">{[direct ? "assigned directly" : "", groups.length ? `through ${groups.join(", ")}` : ""].filter(Boolean).join("; ")}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
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
