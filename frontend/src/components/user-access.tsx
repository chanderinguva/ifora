"use client";

import Link from "next/link";
import { Badge } from "@/components/bits";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { AdminRolesCard } from "@/components/admin-roles-card";
import type { User } from "@/lib/types";

/** The "Groups and Roles" tab of a user: the groups they belong to, and (for administrators) the roles they hold and where each comes from. */
export function UserGroupsAndRoles({ user, viewerIsSuperAdmin }: { user: User; viewerIsSuperAdmin: boolean }) {
  const groups = user.groups ?? [];
  return (
    <>
      <Card className="mb-6" data-testid="user-groups">
        <CardHeader><CardTitle>Groups ({groups.length})</CardTitle></CardHeader>
        <CardContent>
          {groups.length > 0 ? (
            <ul className="divide-y text-sm">
              {groups.map((g) => (
                <li key={g.id} className="flex items-center justify-between gap-3 py-2" data-testid="user-group-row">
                  <Link className="font-medium underline-offset-4 hover:underline" href={`/admin/groups/${g.id}`}>{g.name}</Link>
                  {g.type && <Badge tone="neutral"><span className="capitalize">{g.type}</span></Badge>}
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-muted-foreground">Not a member of any group.</p>
          )}
        </CardContent>
      </Card>

      {user.is_super_admin ? (
        <Card className="mb-6" data-testid="user-roles-note">
          <CardHeader><CardTitle>Administrator roles</CardTitle></CardHeader>
          <CardContent className="text-sm text-muted-foreground">Super administrators hold every administrator role. Roles are not assigned to them.</CardContent>
        </Card>
      ) : !user.is_admin ? (
        <Card className="mb-6" data-testid="user-roles-note">
          <CardHeader><CardTitle>Administrator roles</CardTitle></CardHeader>
          <CardContent className="text-sm text-muted-foreground">This person is not an administrator, so they hold no administrator roles.</CardContent>
        </Card>
      ) : viewerIsSuperAdmin ? (
        <AdminRolesCard userId={user.id} />
      ) : (
        <Card className="mb-6" data-testid="user-roles-note">
          <CardHeader><CardTitle>Administrator roles</CardTitle></CardHeader>
          <CardContent className="text-sm text-muted-foreground">Only super administrators can see or change another administrator&apos;s roles.</CardContent>
        </Card>
      )}
    </>
  );
}
