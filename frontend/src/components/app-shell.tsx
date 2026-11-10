"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { usePathname } from "next/navigation";
import { Menu, Search, PanelLeftClose, PanelLeftOpen, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { useCurrentUser } from "./auth-guard";
import { Breadcrumbs } from "./breadcrumbs";
import { Logo, LogoLink } from "./logo";
import { SidebarNav, type NavGroup } from "./sidebar-nav";
import { ThemeToggle } from "./theme-toggle";
import { UserMenu } from "./user-menu";

export type { NavGroup, NavItem } from "./sidebar-nav";

const COLLAPSE_KEY = "ifora.sidebar";
const LEGACY_COLLAPSE_KEY = "identityforge.sidebar"; // read once so a collapsed rail stays collapsed after the rebrand
const iconButton =
  "inline-flex h-9 w-9 items-center justify-center rounded-md border text-muted-foreground outline-none hover:bg-accent hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring";

/** Overlay navigation for small screens: Escape and backdrop close it, focus is trapped and restored. */
function MobileDrawer({ open, onClose, groups, home, title }: { open: boolean; onClose: () => void; groups: NavGroup[]; home: string; title: string }) {
  const panel = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const previous = document.activeElement as HTMLElement | null;
    panel.current?.querySelector<HTMLElement>("a[href]")?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") return onClose();
      if (e.key !== "Tab" || !panel.current) return;
      const f = [...panel.current.querySelectorAll<HTMLElement>("a[href],button:not([disabled])")];
      if (!f.length) return;
      if (e.shiftKey && document.activeElement === f[0]) (e.preventDefault(), f[f.length - 1].focus());
      else if (!e.shiftKey && document.activeElement === f[f.length - 1]) (e.preventDefault(), f[0].focus());
    };
    document.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
      previous?.focus();
    };
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-40 md:hidden">
      <div className="absolute inset-0 bg-black/50" aria-hidden="true" onClick={onClose} />
      <div ref={panel} role="dialog" aria-modal="true" aria-label="Navigation" data-testid="mobile-drawer" className="absolute inset-y-0 left-0 flex w-72 max-w-[85vw] flex-col bg-background shadow-xl">
        <div className="flex h-14 items-center justify-between border-b px-5">
          <Logo href={home} />
          <button className={iconButton} aria-label="Close navigation" onClick={onClose}>
            <X className="h-4 w-4" aria-hidden="true" />
          </button>
        </div>
        <SidebarNav groups={groups} onNavigate={onClose} />
      </div>
    </div>
  );
}

export function AppShell({ title, nav, children }: { title: string; nav: NavGroup[]; children: React.ReactNode }) {
  const user = useCurrentUser();
  const pathname = usePathname();
  const home = nav[0].items[0].href;

  const [collapsed, setCollapsed] = useState(false);
  const [ready, setReady] = useState(false); // no width animation on first paint
  const [drawer, setDrawer] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [stepUp, setStepUp] = useState(false);

  useEffect(() => {
    try {
      setCollapsed((localStorage.getItem(COLLAPSE_KEY) ?? localStorage.getItem(LEGACY_COLLAPSE_KEY)) === "1");
    } catch {
      /* storage unavailable: stay expanded */
    }
    setReady(true);
  }, []);
  useEffect(() => setDrawer(false), [pathname]);

  const toggleCollapsed = () =>
    setCollapsed((c) => {
      try {
        localStorage.setItem(COLLAPSE_KEY, c ? "0" : "1");
      } catch {
        /* ignore */
      }
      return !c;
    });
  const closeDrawer = useCallback(() => setDrawer(false), []);

  return (
    <div className="flex min-h-screen bg-muted/30">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-3 focus:top-3 focus:z-50 focus:rounded-md focus:border focus:bg-background focus:px-3 focus:py-2 focus:text-sm focus:shadow">
        Skip to main content
      </a>

      <aside
        id="sidebar"
        aria-label={title}
        data-collapsed={collapsed}
        className={cn(
          "hidden shrink-0 flex-col border-r bg-background md:flex",
          collapsed ? "w-16" : "w-60",
          ready && "transition-[width] duration-200 ease-in-out motion-reduce:transition-none",
        )}
      >
        <div className={cn("flex h-14 shrink-0 items-center border-b", collapsed ? "justify-center" : "px-5")}>
          {collapsed ? <LogoLink href={home} /> : <Logo href={home} />}
        </div>
        <SidebarNav groups={nav} collapsed={collapsed} />
      </aside>

      <MobileDrawer open={drawer} onClose={closeDrawer} groups={nav} home={home} title={title} />

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 items-center gap-3 border-b bg-background px-4 md:px-6">
          <button className={cn(iconButton, "md:hidden")} aria-label="Open navigation" aria-expanded={drawer} data-testid="open-nav" onClick={() => setDrawer(true)}>
            <Menu className="h-4 w-4" aria-hidden="true" />
          </button>
          <button
            className={cn(iconButton, "hidden md:inline-flex")}
            aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            aria-expanded={!collapsed}
            aria-controls="sidebar"
            data-testid="toggle-sidebar"
            onClick={toggleCollapsed}
          >
            {collapsed ? <PanelLeftOpen className="h-4 w-4" aria-hidden="true" /> : <PanelLeftClose className="h-4 w-4" aria-hidden="true" />}
          </button>
          <LogoLink href={home} className="md:hidden" />
          <Breadcrumbs groups={nav} className="hidden sm:block" />
          <div className="ml-auto flex items-center gap-2 sm:gap-3">
            {user.is_admin && !user.acting_as_user && (
              <button className={cn(iconButton, "w-auto gap-2 px-3 text-sm text-muted-foreground")} aria-label="Search" data-testid="open-search"
                onClick={() => window.dispatchEvent(new Event("open-command-palette"))}>
                <Search className="h-4 w-4" aria-hidden="true" />
                <span className="hidden sm:inline">Search</span>
                <kbd className="hidden rounded border px-1 text-[10px] sm:inline">⌘K</kbd>
              </button>
            )}
            <ThemeToggle />
            <UserMenu open={menuOpen} onOpenChange={setMenuOpen} stepUp={stepUp} onStepUpChange={setStepUp} />
          </div>
        </header>

        {user.is_admin && user.acting_as_user && (
          <div role="status" data-testid="user-view-banner" className="flex flex-wrap items-center justify-between gap-2 border-b bg-amber-50 px-6 py-2 text-sm text-amber-900 dark:bg-amber-950 dark:text-amber-200">
            <span>You are in <strong>user view</strong>. Administrator functions are switched off for this session.</span>
            <button
              className="underline underline-offset-4"
              onClick={() => {
                setMenuOpen(true);
                setStepUp(true);
              }}
            >
              Switch to admin view
            </button>
          </div>
        )}
        <main id="main" tabIndex={-1} className="flex-1 p-4 outline-none md:p-6">
          {children}
        </main>
      </div>
    </div>
  );
}
