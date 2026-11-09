"use client";

import { LayoutDashboard, Users, Shield, ScrollText, Home, Settings, Workflow, AppWindow, SlidersHorizontal, RefreshCw, Send, Zap, LayoutGrid, Globe, Palette, Mail, KeyRound, Inbox } from "lucide-react";
import { AppShell, type NavGroup } from "./app-shell";
import { useCurrentUser } from "./auth-guard";
import { inAdminView } from "@/lib/roles";
import { CommandPalette } from "./command-palette";
import { useEffect, useState } from "react";
import { http } from "@/lib/http";

export const ADMIN_NAV: NavGroup[] = [
  { items: [{ href: "/admin/dashboard", area: "overview", label: "Dashboard", icon: LayoutDashboard }] },
  {
    label: "Directory",
    items: [
      { href: "/admin/users", area: "users", label: "Users", icon: Users },
      { href: "/admin/groups", area: "groups", label: "Groups", icon: Shield },
      { href: "/admin/profile-editor", area: "directory_settings", label: "Profile editor", icon: SlidersHorizontal },
      { href: "/admin/group-rules", area: "groups", label: "Group rules", icon: Workflow },
    ],
  },
  { label: "Automation", items: [{ href: "/admin/recipes", area: "automation", label: "Recipes", icon: Zap }] },
  {
    label: "Applications",
    items: [
      { href: "/admin/applications", area: "applications", label: "Applications", icon: LayoutGrid },
      { href: "/admin/access-requests", area: "applications", label: "Access requests", icon: Inbox },
      { href: "/admin/oidc-clients", area: "applications", label: "OIDC clients", icon: AppWindow },
      { href: "/admin/app-provisioning", area: "applications", label: "Provisioning apps", icon: Send },
      { href: "/admin/provisioning", area: "applications", label: "Inbound SCIM", icon: RefreshCw },
    ],
  },
  { label: "Customization", items: [{ href: "/admin/branding", label: "Branding", icon: Palette, area: "branding" }, { href: "/admin/email-templates", label: "Email templates", icon: Mail, area: "branding" }] },
  { label: "Security", items: [{ href: "/admin/security-policy", area: "security", label: "Password & sessions", icon: KeyRound }, { href: "/admin/network-zones", area: "security", label: "Network zones", icon: Globe }, { href: "/admin/audit", area: "reports", label: "System log", icon: ScrollText }] },
  { label: "Account", items: [{ href: "/settings", label: "Account settings", icon: Settings }] },
];

export const USER_NAV: NavGroup[] = [
  { items: [{ href: "/dashboard", label: "Home", icon: Home }, { href: "/apps", label: "My apps", icon: LayoutGrid }, { href: "/apps/request", label: "Request access", icon: KeyRound }] },
  { label: "Account", items: [{ href: "/settings", label: "Account settings", icon: Settings }] },
];

/** Picks the navigation for the signed-in user's role. */
export function RoleShell({ children }: { children: React.ReactNode }) {
  const user = useCurrentUser();
  const admin = inAdminView(user);
  // What this administrator's roles allow; until it loads (or if it fails) show everything, the server enforces anyway.
  const [access, setAccess] = useState<Record<string, string> | null>(null);
  useEffect(() => {
    if (admin) http<{ access: Record<string, string> }>("/me/admin-access").then((r) => setAccess(r.access)).catch(() => {});
  }, [admin]);
  const nav = admin && access
    ? ADMIN_NAV.map((g) => ({ ...g, items: g.items.filter((i) => !i.area || access[i.area]) })).filter((g) => g.items.length > 0)
    : ADMIN_NAV;
  return (
    <AppShell title={admin ? "Administration" : "My account"} nav={admin ? nav : USER_NAV}>
      {children}
      {admin && <CommandPalette nav={nav} />}
    </AppShell>
  );
}
