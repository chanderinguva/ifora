"use client";

import { AuthGuard } from "@/components/auth-guard";
import { RoleShell } from "@/components/role-shell";
import { StepUpProvider } from "@/components/step-up-dialog";

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  return (
    <AuthGuard requireAdmin>
      <StepUpProvider>
        <RoleShell>{children}</RoleShell>
      </StepUpProvider>
    </AuthGuard>
  );
}
