"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { getCurrentUser } from "@/lib/auth-client";

/** Entry point: send people where their role belongs. */
export default function HomePage() {
  const router = useRouter();
  useEffect(() => {
    getCurrentUser().then((u) => router.replace(!u ? "/login" : u.is_admin ? "/admin/dashboard" : "/dashboard"));
  }, [router]);
  return <div className="p-8 text-sm text-muted-foreground">Loading…</div>;
}
