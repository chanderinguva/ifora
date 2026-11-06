"use client";

import { AuthGuard } from "@/components/auth-guard";
import { RoleShell } from "@/components/role-shell";

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  return (
    <AuthGuard requireAdmin>
      <RoleShell>{children}</RoleShell>
    </AuthGuard>
  );
}
