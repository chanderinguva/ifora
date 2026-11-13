"use client";
import { Badge } from "@/components/bits";
import type { User } from "@/lib/types";

export function UserRoleBadges({ user }: { user: Pick<User, "is_admin" | "is_super_admin" | "admin_roles"> }) {
  if (user.is_super_admin) return <Badge tone="info">Super admin</Badge>;
  if (user.admin_roles?.length) return <div className="flex flex-wrap gap-1">
    {user.admin_roles.map((role) => <span key={role.id}
      title={role.sources.includes("group") ? "Granted through a group" + (role.sources.includes("direct") ? " and directly" : "") : "Assigned directly"}>
      <Badge tone="info">{role.label}</Badge>
    </span>)}
  </div>;
  return user.is_admin ? <Badge tone="info">{user.admin_roles ? "Admin (no role assigned)" : "Admin (roles unavailable)"}</Badge> : <Badge>User</Badge>;
}
