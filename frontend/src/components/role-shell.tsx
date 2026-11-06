"use client";

import { LayoutDashboard, Users, Shield, ScrollText, Home, Settings } from "lucide-react";
import { AppShell, type NavItem } from "./app-shell";
import { useCurrentUser } from "./auth-guard";

export const ADMIN_NAV: NavItem[] = [
  { href: "/admin/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { href: "/admin/users", label: "Users", icon: Users },
  { href: "/admin/groups", label: "Groups", icon: Shield },
  { href: "/admin/audit", label: "Audit log", icon: ScrollText },
  { href: "/settings", label: "Account settings", icon: Settings },
];

export const USER_NAV: NavItem[] = [
  { href: "/dashboard", label: "Home", icon: Home },
  { href: "/settings", label: "Account settings", icon: Settings },
];

/** Picks the navigation for the signed-in user's role. */
export function RoleShell({ children }: { children: React.ReactNode }) {
  const user = useCurrentUser();
  return (
    <AppShell title={user.is_admin ? "Administration" : "My account"} nav={user.is_admin ? ADMIN_NAV : USER_NAV}>
      {children}
    </AppShell>
  );
}
