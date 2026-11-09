"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { http } from "@/lib/http";

type Role = { id: string; label: string; description: string };

/** Super administrators only: administrator roles every member of this team group receives (ADR 019). */
export function GroupRolesCard({ groupId, groupType, members }: { groupId: number; groupType: string; members: number }) {
  const [catalog, setCatalog] = useState<Role[]>([]);
  const [roles, setRoles] = useState<string[]>([]);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [allowed, setAllowed] = useState<boolean | null>(null);

  useEffect(() => {
    http<{ items: Role[] }>("/admin/roles").then((r) => setCatalog(r.items)).then(() => setAllowed(true)).catch(() => setAllowed(false));
    http<{ roles: string[] }>(`/admin/roles/groups/${groupId}`).then((r) => setRoles(r.roles)).catch(() => {});
  }, [groupId, groupType]);

  if (!allowed) return null; // only super administrators can read the role catalogue
  const toggle = (id: string) => setRoles((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id]));
  async function save() {
    setMsg(null);
    try {
      const r = await http<{ roles: string[] }>(`/admin/roles/groups/${groupId}`, { method: "PUT", body: { roles } });
      setRoles(r.roles);
      setMsg({ ok: true, text: `Roles saved for ${members} member${members === 1 ? "" : "s"}; they apply on each administrator's next request` });
    } catch (e) { setMsg({ ok: false, text: e instanceof Error ? e.message : "Failed" }); }
  }
  return (
    <Card className="mb-6" data-testid="group-roles">
      <CardHeader><CardTitle>Administrator roles</CardTitle></CardHeader>
      <CardContent className="space-y-3 text-sm">
        <p className="text-muted-foreground">
          Everyone in this group gets the selected roles (only team groups can carry roles, and only super administrators can change who is in a group that does).
          {groupType !== "team" && " Set the group type to Team to use this."}
        </p>
        {msg && <Alert variant={msg.ok ? "default" : "destructive"} role="status"><AlertDescription>{msg.text}</AlertDescription></Alert>}
        {catalog.map((r) => (
          <label key={r.id} className="flex items-start gap-2">
            <input type="checkbox" className="mt-1" disabled={groupType !== "team"} checked={roles.includes(r.id)} onChange={() => toggle(r.id)} data-testid={`group-role-${r.id}`} />
            <span><span className="font-medium">{r.label}</span><span className="block text-xs text-muted-foreground">{r.description}</span></span>
          </label>
        ))}
        <Button size="sm" disabled={groupType !== "team" && roles.length === 0} onClick={save} data-testid="group-roles-save">Save roles</Button>
      </CardContent>
    </Card>
  );
}
