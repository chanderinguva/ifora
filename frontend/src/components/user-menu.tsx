"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { LogOut, Settings, ShieldCheck, UserRound } from "lucide-react";
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
  const fullName = [user.first_name, user.last_name].filter(Boolean).join(" ");
  const initials = (((user.first_name?.[0] ?? "") + (user.last_name?.[0] ?? "")) || (user.email?.[0] ?? "?")).toUpperCase();

  return (
    <div className="relative text-sm" ref={menuRef}>
      <button
        data-testid="user-menu"
        aria-haspopup="menu"
        aria-expanded={open}
        title={roleLabel ? `${user.email} · ${roleLabel}` : user.email}
        className="inline-flex h-9 w-9 items-center justify-center rounded-full bg-primary text-xs font-semibold text-primary-foreground outline-none ring-offset-background hover:opacity-90 focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
        onClick={() => onOpenChange(!open)}
      >
        <span aria-hidden="true">{initials}</span>
        {/* the account stays in the accessible name (and the DOM) even though only the initials are drawn */}
        <span className="sr-only">
          <span data-testid="current-user">{user.email}</span>{roleLabel ? ` ${roleLabel}` : ""}
        </span>
      </button>
      {open && (
        <div role="menu" className="absolute right-0 z-20 mt-2 w-64 rounded-md border bg-popover p-1 text-popover-foreground shadow-md">
          <div className="mb-1 border-b px-3 py-2" data-testid="user-menu-header">
            {fullName && <div className="truncate font-medium">{fullName}</div>}
            <div className="truncate text-xs text-muted-foreground">{user.email}</div>
            {roleLabel && <div className="mt-0.5 text-xs capitalize text-muted-foreground">{roleLabel}</div>}
          </div>
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
