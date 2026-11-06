"use client";

import { AuthGuard } from "@/components/auth-guard";
import { RoleShell } from "@/components/role-shell";

export default function UserLayout({ children }: { children: React.ReactNode }) {
  return (
    <AuthGuard>
      <RoleShell>{children}</RoleShell>
    </AuthGuard>
  );
}
