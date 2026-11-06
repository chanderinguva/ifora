"use client";

import { AuthGuard } from "@/components/auth-guard";
import { RoleShell } from "@/components/role-shell";

/** Account settings are available to everyone, inside the shell that matches their role. */
export default function SettingsLayout({ children }: { children: React.ReactNode }) {
  return (
    <AuthGuard>
      <RoleShell>{children}</RoleShell>
    </AuthGuard>
  );
}
