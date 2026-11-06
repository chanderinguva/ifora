"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { ChevronDown, LogOut, Settings, type LucideIcon } from "lucide-react";
import { logout } from "@/lib/auth-client";
import { cn } from "@/lib/utils";
import { useCurrentUser } from "./auth-guard";
import { ThemeToggle } from "./theme-toggle";

export type NavItem = { href: string; label: string; icon: LucideIcon };

export function AppShell({
  title,
  nav,
  children,
}: {
  title: string;
  nav: NavItem[];
  children: React.ReactNode;
}) {
  const user = useCurrentUser();
  const pathname = usePathname();
  const router = useRouter();
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const close = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setMenuOpen(false);
    };
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setMenuOpen(false);
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", esc);
    };
  }, []);

  return (
    <div className="flex min-h-screen bg-muted/30">
      <aside className="hidden w-60 shrink-0 flex-col border-r bg-background md:flex">
        <div className="border-b px-5 py-4">
          <div className="text-lg font-semibold">IdentityForge</div>
          <div className="text-xs text-muted-foreground">{title}</div>
        </div>
        <nav className="flex-1 space-y-1 p-3" aria-label="Main">
          {nav.map(({ href, label, icon: Icon }) => {
            const active = pathname === href || pathname.startsWith(href + "/");
            return (
              <Link
                key={href}
                href={href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium",
                  active ? "bg-accent text-accent-foreground" : "text-muted-foreground hover:bg-accent/60",
                )}
              >
                <Icon className="h-4 w-4" />
                {label}
              </Link>
            );
          })}
        </nav>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center justify-between border-b bg-background px-6 py-3">
          <nav className="flex gap-3 md:hidden" aria-label="Mobile">
            {nav.map(({ href, label }) => (
              <Link key={href} href={href} className="text-sm underline-offset-4 hover:underline">
                {label}
              </Link>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-3">
          <ThemeToggle />
          <div className="relative text-sm" ref={menuRef}>
            <button
              data-testid="user-menu"
              aria-haspopup="menu"
              aria-expanded={menuOpen}
              className="inline-flex items-center gap-2 rounded-md border px-3 py-1.5 hover:bg-accent"
              onClick={() => setMenuOpen((v) => !v)}
            >
              <span data-testid="current-user">{user.email}</span>
              <span className="text-xs text-muted-foreground">
                {user.is_super_admin ? "super admin" : user.is_admin ? "admin" : ""}
              </span>
              <ChevronDown className="h-4 w-4" />
            </button>
            {menuOpen && (
              <div role="menu" className="absolute right-0 z-20 mt-2 w-56 rounded-md border bg-background p-1 shadow-md">
                <Link
                  role="menuitem"
                  href="/settings"
                  className="flex items-center gap-2 rounded px-3 py-2 hover:bg-accent"
                  onClick={() => setMenuOpen(false)}
                >
                  <Settings className="h-4 w-4" /> Account settings
                </Link>
                <button
                  role="menuitem"
                  className="flex w-full items-center gap-2 rounded px-3 py-2 text-left hover:bg-accent"
                  onClick={async () => {
                    try {
                      await logout();
                    } finally {
                      router.replace("/login");
                    }
                  }}
                >
                  <LogOut className="h-4 w-4" /> Log out
                </button>
              </div>
            )}
          </div>
          </div>
        </header>
        <main className="flex-1 p-6">{children}</main>
      </div>
    </div>
  );
}
