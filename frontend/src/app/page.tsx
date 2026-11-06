"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { getCurrentUser } from "@/lib/auth-client";
import { inAdminView } from "@/lib/roles";

/** Entry point: send people where their role belongs. */
export default function HomePage() {
  const router = useRouter();
  useEffect(() => {
    getCurrentUser().then((u) => router.replace(!u ? "/login" : u.mfa_setup_required ? "/settings#security" : inAdminView(u) ? "/admin/dashboard" : "/dashboard"));
  }, [router]);
  return <div className="p-8 text-sm text-muted-foreground">Loading…</div>;
}
