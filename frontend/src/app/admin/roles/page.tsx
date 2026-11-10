"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge, PageHeader, fieldClass } from "@/components/bits";
import { useCurrentUser } from "@/components/auth-guard";
import { http, qs, type Page } from "@/lib/http";
import type { Group } from "@/lib/types";

type Role = { id: string; label: string; description: string; access: Record<string, string> };
type Holder = { group_id: number; name: string; roles: string[] };
const msgOf = (e: unknown) => (e instanceof Error ? e.message : "Failed");

/** Roles, seen from the role's side: which groups hold each administrator role. Everyone in a team or role based group that holds a role has it (ADR 019). */
export default function RolesPage() {
  const me = useCurrentUser();
  const [roles, setRoles] = useState<Role[]>([]);
  const [holders, setHolders] = useState<Holder[]>([]);
  const [teams, setTeams] = useState<Group[]>([]);
  const [members, setMembers] = useState<Record<number, number>>({});
  const [pick, setPick] = useState<Record<string, string>>({});
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const load = useCallback(async () => {
    try {
      const [r, h, ...kinds] = await Promise.all([
        http<{ items: Role[] }>("/admin/roles"),
        http<{ items: Holder[] }>("/admin/roles/groups"),
        ...["team", "role"].map((type) => http<Page<Group>>(`/admin/groups${qs({ count: 100, filter: `type eq "${type}"`, sortBy: "name" })}`)),
      ]);
      setRoles(r.items); setHolders(h.items);
      const team = kinds.flatMap((k) => k.Resources).filter((g) => !g.is_system_group).sort((a, b) => a.name.localeCompare(b.name));
      setTeams(team);
      setMembers(Object.fromEntries(team.map((g) => [g.id, g.member_count])));
    } catch (e) { setMsg({ ok: false, text: msgOf(e) }); }
  }, []);
  useEffect(() => { void load(); }, [load]);

  if (!me.is_super_admin) {
    return <div className="max-w-4xl"><PageHeader title="Roles" /><Alert data-testid="roles-forbidden"><AlertDescription>Only super administrators can assign administrator roles.</AlertDescription></Alert></div>;
  }

  async function change(roleId: string, groupId: number, add: boolean) {
    setMsg(null);
    const current = holders.find((h) => h.group_id === groupId)?.roles ?? [];
    const next = add ? Array.from(new Set([...current, roleId])) : current.filter((x) => x !== roleId);
    const label = roles.find((r) => r.id === roleId)?.label ?? roleId;
    const name = holders.find((h) => h.group_id === groupId)?.name ?? teams.find((g) => g.id === groupId)?.name ?? "the group";
    try {
      await http(`/admin/roles/groups/${groupId}`, { method: "PUT", body: { roles: next } });
      setMsg({ ok: true, text: add ? `${name} now holds ${label}; its members get it on their next request` : `${name} no longer holds ${label}` });
      setPick((p) => ({ ...p, [roleId]: "" }));
      await load();
    } catch (e) { setMsg({ ok: false, text: msgOf(e) }); }
  }

  return (
    <div className="max-w-4xl">
      <PageHeader title="Roles" />
      <p className="mb-4 text-sm text-muted-foreground">
        An administrator role decides what a person can do in the admin area. Give a role to a <strong>team</strong> or <strong>role based</strong> group and everyone in that group holds it.
        Roles can also be given to one person on their user page (Groups and Roles tab). Only team and role based groups can hold roles; change a group&apos;s type on its page first.
      </p>
      {msg && <Alert variant={msg.ok ? "default" : "destructive"} className="mb-4" role="status" data-testid="roles-msg"><AlertDescription>{msg.text}</AlertDescription></Alert>}

      <div className="space-y-4">
        {roles.map((role) => {
          const holding = holders.filter((h) => h.roles.includes(role.id));
          const available = teams.filter((g) => !holding.some((h) => h.group_id === g.id));
          const areas = Object.entries(role.access).filter(([, level]) => level);
          return (
            <Card key={role.id} data-testid={`role-card-${role.id}`}>
              <CardHeader className="pb-2">
                <CardTitle className="text-base">{role.label}</CardTitle>
                <p className="text-sm text-muted-foreground">{role.description}</p>
                {areas.length > 0 && (
                  <div className="flex flex-wrap gap-1 pt-1" aria-label={`${role.label} access`}>
                    {areas.map(([area, level]) => <Badge key={area} tone={level === "write" ? "info" : "neutral"}>{area.replace(/_/g, " ")}: {level}</Badge>)}
                  </div>
                )}
              </CardHeader>
              <CardContent className="space-y-3 text-sm">
                <div>
                  <div className="mb-1 font-medium">Groups with this role ({holding.length})</div>
                  {holding.length === 0 ? (
                    <p className="text-muted-foreground" data-testid={`role-empty-${role.id}`}>No group holds this role.</p>
                  ) : (
                    <ul className="divide-y rounded-md border">
                      {holding.map((h) => (
                        <li key={h.group_id} className="flex items-center justify-between gap-3 px-3 py-2" data-testid={`role-holder-${role.id}`}>
                          <span><Link className="font-medium underline-offset-4 hover:underline" href={`/admin/groups/${h.group_id}`}>{h.name}</Link>
                            {members[h.group_id] !== undefined && <span className="ml-2 text-xs text-muted-foreground">{members[h.group_id]} member{members[h.group_id] === 1 ? "" : "s"}</span>}</span>
                          <Button size="sm" variant="outline" aria-label={`Remove ${h.name} from ${role.label}`}
                            onClick={() => { if (window.confirm(`Remove ${role.label} from ${h.name}? Its members lose this role on their next request.`)) void change(role.id, h.group_id, false); }}>Remove</Button>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <select aria-label={`Add a group to ${role.label}`} className={fieldClass + " !w-72"} value={pick[role.id] ?? ""} disabled={available.length === 0}
                    onChange={(e) => setPick((p) => ({ ...p, [role.id]: e.target.value }))}>
                    <option value="">{available.length === 0 ? "No more groups" : "Choose a group…"}</option>
                    {available.map((g) => <option key={g.id} value={g.id}>{g.name} ({g.member_count})</option>)}
                  </select>
                  <Button size="sm" disabled={!pick[role.id]} onClick={() => void change(role.id, Number(pick[role.id]), true)} aria-label={`Add group to ${role.label}`}>Add group</Button>
                </div>
              </CardContent>
            </Card>
          );
        })}
      </div>
      {teams.length === 0 && roles.length > 0 && (
        <p className="mt-4 text-sm text-muted-foreground" data-testid="roles-no-teams">
          There are no team or role based groups yet. Create one (it needs an owner) on the <Link className="underline underline-offset-4" href="/admin/groups">Groups</Link> page, or change an existing group&apos;s type.
        </p>
      )}
    </div>
  );
}
