"use client";

import { UserCircle } from "lucide-react";
import { AuthGuard } from "@/components/auth-guard";
import { AppShell } from "@/components/app-shell";

export default function UserLayout({ children }: { children: React.ReactNode }) {
  return (
    <AuthGuard>
      <AppShell title="My account" nav={[{ href: "/dashboard", label: "My account", icon: UserCircle }]}>
        {children}
      </AppShell>
    </AuthGuard>
  );
}
