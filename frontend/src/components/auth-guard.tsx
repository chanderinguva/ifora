"use client";

import { createContext, useContext, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { getCurrentUser } from "@/lib/auth-client";
import { inAdminView } from "@/lib/roles";
import { setDisplayPrefs } from "@/lib/display";
import type { User } from "@/lib/types";

const UserContext = createContext<User | null>(null);
export const useCurrentUser = () => useContext(UserContext) as User;

/** UI-level gate. The API enforces authorization; this only avoids showing dead pages. */
export function AuthGuard({
  requireAdmin = false,
  children,
}: {
  requireAdmin?: boolean;
  children: React.ReactNode;
}) {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);

  useEffect(() => {
    let alive = true;
    getCurrentUser().then((u: User | null) => {
      if (!alive) return;
      if (!u) router.replace("/login");
      else if (requireAdmin && u.mfa_setup_required) router.replace("/settings#security");
      else if (requireAdmin && !inAdminView(u)) router.replace("/dashboard");
      else {
        setDisplayPrefs(u.profile_attributes);
        setUser(u);
      }
    });
    return () => {
      alive = false;
    };
  }, [router, requireAdmin]);

  if (!user) {
    return <div className="p-8 text-sm text-muted-foreground">Loading…</div>;
  }
  return <UserContext.Provider value={user}>{children}</UserContext.Provider>;
}
