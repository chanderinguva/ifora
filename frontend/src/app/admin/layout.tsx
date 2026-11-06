"use client";

import { LayoutDashboard, Users, Shield, ScrollText } from "lucide-react";
import { AuthGuard } from "@/components/auth-guard";
import { AppShell } from "@/components/app-shell";

const nav = [
  { href: "/admin/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { href: "/admin/users", label: "Users", icon: Users },
  { href: "/admin/groups", label: "Groups", icon: Shield },
  { href: "/admin/audit", label: "Audit log", icon: ScrollText },
];

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  return (
    <AuthGuard requireAdmin>
      <AppShell title="Administration" nav={nav}>
        {children}
      </AppShell>
    </AuthGuard>
  );
}
