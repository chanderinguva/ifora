"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { LogOut, type LucideIcon } from "lucide-react";
import { logout } from "@/lib/auth-client";
import { cn } from "@/lib/utils";
import { useCurrentUser } from "./auth-guard";

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
          <div className="ml-auto flex items-center gap-4 text-sm">
            <span className="text-muted-foreground" data-testid="current-user">
              {user.email}
              {user.is_super_admin ? " · super admin" : user.is_admin ? " · admin" : ""}
            </span>
            <button
              className="inline-flex items-center gap-1 rounded-md border px-3 py-1.5 hover:bg-accent"
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
        </header>
        <main className="flex-1 p-6">{children}</main>
      </div>
    </div>
  );
}
