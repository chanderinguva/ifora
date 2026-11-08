"use client";

import { LayoutDashboard, Users, Shield, ScrollText, Home, Settings, Workflow, AppWindow, SlidersHorizontal, RefreshCw, Send, Zap, LayoutGrid } from "lucide-react";
import { AppShell, type NavGroup } from "./app-shell";
import { useCurrentUser } from "./auth-guard";
import { inAdminView } from "@/lib/roles";
import { CommandPalette } from "./command-palette";

export const ADMIN_NAV: NavGroup[] = [
  { items: [{ href: "/admin/dashboard", label: "Dashboard", icon: LayoutDashboard }] },
  {
    label: "Directory",
    items: [
      { href: "/admin/users", label: "Users", icon: Users },
      { href: "/admin/groups", label: "Groups", icon: Shield },
      { href: "/admin/profile-editor", label: "Profile editor", icon: SlidersHorizontal },
      { href: "/admin/group-rules", label: "Group rules", icon: Workflow },
    ],
  },
  { label: "Automation", items: [{ href: "/admin/recipes", label: "Recipes", icon: Zap }] },
  {
    label: "Applications",
    items: [
      { href: "/admin/applications", label: "Applications", icon: LayoutGrid },
      { href: "/admin/oidc-clients", label: "OIDC clients", icon: AppWindow },
      { href: "/admin/app-provisioning", label: "Provisioning apps", icon: Send },
      { href: "/admin/provisioning", label: "Inbound SCIM", icon: RefreshCw },
    ],
  },
  { label: "Security", items: [{ href: "/admin/audit", label: "Audit log", icon: ScrollText }] },
  { label: "Account", items: [{ href: "/settings", label: "Account settings", icon: Settings }] },
];

export const USER_NAV: NavGroup[] = [
  { items: [{ href: "/dashboard", label: "Home", icon: Home }, { href: "/apps", label: "My apps", icon: LayoutGrid }] },
  { label: "Account", items: [{ href: "/settings", label: "Account settings", icon: Settings }] },
];

/** Picks the navigation for the signed-in user's role. */
export function RoleShell({ children }: { children: React.ReactNode }) {
  const user = useCurrentUser();
  const admin = inAdminView(user);
  return (
    <AppShell title={admin ? "Administration" : "My account"} nav={admin ? ADMIN_NAV : USER_NAV}>
      {children}
      {admin && <CommandPalette nav={ADMIN_NAV} />}
    </AppShell>
  );
}
