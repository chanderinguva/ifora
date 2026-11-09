"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { http } from "@/lib/http";

type Role = { id: string; label: string; description: string };

/** Super administrators only: which administrator roles this admin holds. No role means full organization administrator. */
export function AdminRolesCard({ userId }: { userId: number }) {
  const [catalog, setCatalog] = useState<Role[]>([]);
  const [roles, setRoles] = useState<string[]>([]);
  const [implicit, setImplicit] = useState(true);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  useEffect(() => {
    http<{ items: Role[] }>("/admin/roles").then((r) => setCatalog(r.items.filter((x) => x.id !== "org_admin"))).catch(() => {});
    http<{ roles: string[]; implicit: boolean }>(`/admin/roles/users/${userId}`).then((r) => { setRoles(r.roles); setImplicit(r.implicit); }).catch((e) => setMsg({ ok: false, text: e.message }));
  }, [userId]);

  const toggle = (id: string) => setRoles((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id]));
  async function save() {
    setMsg(null);
    try {
      const r = await http<{ roles: string[]; implicit: boolean }>(`/admin/roles/users/${userId}`, { method: "PUT", body: { roles } });
      setRoles(r.roles); setImplicit(r.implicit); setMsg({ ok: true, text: "Roles saved; they apply on the administrator's next request" });
    } catch (e) { setMsg({ ok: false, text: e instanceof Error ? e.message : "Failed" }); }
  }

  return (
    <Card className="mb-6" data-testid="admin-roles">
      <CardHeader><CardTitle>Administrator roles</CardTitle></CardHeader>
      <CardContent className="space-y-3 text-sm">
        <p className="text-muted-foreground">{implicit && roles.length === 0 ? "No role is selected, so this administrator has full organization-administrator access." : "This administrator can only do what the selected roles allow."}</p>
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
