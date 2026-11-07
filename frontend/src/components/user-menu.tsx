"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { ChevronDown, LogOut, Settings, ShieldCheck, UserRound } from "lucide-react";
import { logout } from "@/lib/auth-client";
import { http } from "@/lib/http";
import { useCurrentUser } from "./auth-guard";

/** Account menu: account settings, switch role view (admins), log out. State is lifted so the user-view banner can open it. */
export function UserMenu({
  open,
  onOpenChange,
  stepUp,
  onStepUpChange,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  stepUp: boolean;
  onStepUpChange: (v: boolean) => void;
}) {
  const user = useCurrentUser();
  const router = useRouter();
  const menuRef = useRef<HTMLDivElement>(null);
  const [pw, setPw] = useState("");
  const [roleError, setRoleError] = useState<string | null>(null);
  const [switching, setSwitching] = useState(false);

  useEffect(() => {
    const close = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) onOpenChange(false);
    };
    const esc = (e: KeyboardEvent) => e.key === "Escape" && onOpenChange(false);
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", esc);
    };
  }, [onOpenChange]);

  // Full navigations, so every page re-reads /me and shows the right shell for the new view.
  async function switchToUser() {
    setSwitching(true);
    try {
      await http("/me/role/user", { method: "POST" });
      window.location.assign("/dashboard");
    } catch (e) {
      setRoleError(e instanceof Error ? e.message : "Could not switch");
      setSwitching(false);
    }
  }
  async function switchToAdmin(e: React.FormEvent) {
    e.preventDefault();
    setSwitching(true);
    setRoleError(null);
    try {
      await http("/me/role/admin", { method: "POST", body: { password: pw } });
      window.location.assign("/admin/dashboard");
    } catch (err) {
      setRoleError(err instanceof Error ? err.message : "Could not switch");
      setSwitching(false);
    }
  }

  const roleLabel = user.acting_as_user ? "user view" : user.is_super_admin ? "super admin" : user.is_admin ? "admin" : "";

  return (
    <div className="relative text-sm" ref={menuRef}>
      <button
        data-testid="user-menu"
        aria-haspopup="menu"
        aria-expanded={open}
        className="inline-flex items-center gap-2 rounded-md border px-3 py-1.5 outline-none hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring"
        onClick={() => onOpenChange(!open)}
      >
        <span data-testid="current-user" className="max-w-[5.5rem] truncate min-[480px]:max-w-[9rem] sm:max-w-[16rem]">{user.email}</span>
        {roleLabel && <span className="hidden text-xs text-muted-foreground sm:inline">{roleLabel}</span>}
        <ChevronDown className="h-4 w-4" aria-hidden="true" />
      </button>
      {open && (
        <div role="menu" className="absolute right-0 z-20 mt-2 w-60 rounded-md border bg-popover p-1 text-popover-foreground shadow-md">
          <Link role="menuitem" href="/settings" className="flex items-center gap-2 rounded px-3 py-2 hover:bg-accent" onClick={() => onOpenChange(false)}>
            <Settings className="h-4 w-4" aria-hidden="true" /> Account settings
          </Link>
          {user.is_admin && !user.acting_as_user && (
            <button role="menuitem" data-testid="switch-to-user" disabled={switching} className="flex w-full items-center gap-2 rounded px-3 py-2 text-left hover:bg-accent" onClick={switchToUser}>
              <UserRound className="h-4 w-4" aria-hidden="true" /> Switch to user view
            </button>
          )}
          {user.is_admin && user.acting_as_user && !stepUp && (
            <button role="menuitem" data-testid="switch-to-admin" className="flex w-full items-center gap-2 rounded px-3 py-2 text-left hover:bg-accent" onClick={() => onStepUpChange(true)}>
              <ShieldCheck className="h-4 w-4" aria-hidden="true" /> Switch to admin view
            </button>
          )}
          {user.is_admin && user.acting_as_user && stepUp && (
            <form onSubmit={switchToAdmin} className="space-y-2 px-3 py-2" aria-label="Confirm your password">
              <label htmlFor="role-pw" className="text-xs text-muted-foreground">Confirm your password</label>
              <input
                id="role-pw"
                type="password"
                autoComplete="current-password"
                autoFocus
                className="flex h-9 w-full rounded-md border border-input bg-background px-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                value={pw}
                onChange={(e) => setPw(e.target.value)}
              />
              <button type="submit" disabled={!pw || switching} className="h-8 w-full rounded-md bg-primary px-3 text-sm text-primary-foreground disabled:opacity-50">
                Switch to admin view
              </button>
            </form>
          )}
          {roleError && <p role="alert" data-testid="role-error" className="px-3 py-1 text-xs text-destructive">{roleError}</p>}
          <button
            role="menuitem"
            className="flex w-full items-center gap-2 rounded px-3 py-2 text-left hover:bg-accent"
            onClick={async () => {
              try {
                await logout();
              } catch {
                // whatever went wrong, leave the page: the login screen shows the real state of the session
              } finally {
                router.replace("/login");
              }
            }}
          >
            <LogOut className="h-4 w-4" aria-hidden="true" /> Log out
          </button>
        </div>
      )}
    </div>
  );
}
