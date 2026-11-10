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
const WIDTH_KEY = "ifora.sidebar.width";
const DEFAULT_WIDTH = 240; // the former fixed w-60
const MIN_WIDTH = 200;
const MAX_WIDTH = 420;
const clampWidth = (w: number) => Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, Math.round(w)));
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
  const [width, setWidth] = useState(DEFAULT_WIDTH);
  const [dragging, setDragging] = useState(false);
  const aside = useRef<HTMLElement>(null);

  useEffect(() => {
    try {
      setCollapsed((localStorage.getItem(COLLAPSE_KEY) ?? localStorage.getItem(LEGACY_COLLAPSE_KEY)) === "1");
      const saved = Number(localStorage.getItem(WIDTH_KEY));
      if (saved) setWidth(clampWidth(saved));
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

  const saveWidth = (w: number) => {
    try {
      localStorage.setItem(WIDTH_KEY, String(w));
    } catch {
      /* ignore */
    }
  };
  // Drag the right edge of the rail; the keyboard works too (arrows resize, Home/double-click reset).
  const startResize = (e: React.PointerEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.currentTarget.setPointerCapture(e.pointerId);
    setDragging(true);
  };
  const resize = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!dragging || !aside.current) return;
    setWidth(clampWidth(e.clientX - aside.current.getBoundingClientRect().left));
  };
  const endResize = () => {
    if (!dragging) return;
    setDragging(false);
    saveWidth(width);
  };
  const resizeByKey = (e: React.KeyboardEvent<HTMLDivElement>) => {
    const next = e.key === "ArrowLeft" ? width - 16 : e.key === "ArrowRight" ? width + 16 : e.key === "Home" ? DEFAULT_WIDTH : null;
    if (next === null) return;
    e.preventDefault();
    const w = clampWidth(next);
    setWidth(w);
    saveWidth(w);
  };

  return (
    <div className="flex min-h-screen bg-muted/30">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-3 focus:top-3 focus:z-50 focus:rounded-md focus:border focus:bg-background focus:px-3 focus:py-2 focus:text-sm focus:shadow">
        Skip to main content
      </a>

      <aside
        id="sidebar"
        ref={aside}
        aria-label={title}
        data-collapsed={collapsed}
        style={collapsed ? undefined : { width }}
        className={cn(
          "relative hidden shrink-0 flex-col border-r bg-background md:flex",
          collapsed && "w-16",
          ready && !dragging && "transition-[width] duration-200 ease-in-out motion-reduce:transition-none",
        )}
      >
        <div className={cn("flex h-14 shrink-0 items-center border-b", collapsed ? "justify-center" : "px-5")}>
          {collapsed ? <LogoLink href={home} /> : <Logo href={home} />}
        </div>
        <SidebarNav groups={nav} collapsed={collapsed} />
        {!collapsed && (
          <div
            role="separator"
            aria-orientation="vertical"
            aria-label="Resize sidebar"
            aria-valuemin={MIN_WIDTH}
            aria-valuemax={MAX_WIDTH}
            aria-valuenow={width}
            tabIndex={0}
            data-testid="sidebar-resizer"
            title="Drag to resize, double-click to reset"
            className={cn(
              "absolute inset-y-0 -right-1 z-20 w-2 cursor-col-resize touch-none outline-none hover:bg-ring/40 focus-visible:bg-ring/60",
              dragging && "bg-ring/60",
            )}
            onPointerDown={startResize}
            onPointerMove={resize}
            onPointerUp={endResize}
            onPointerCancel={endResize}
            onKeyDown={resizeByKey}
            onDoubleClick={() => {
              setWidth(DEFAULT_WIDTH);
              saveWidth(DEFAULT_WIDTH);
            }}
          />
        )}
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
              <button
                className={cn(iconButton, "w-9 gap-2 bg-muted/40 text-sm sm:w-64 sm:justify-start sm:px-3 lg:w-96 xl:w-[28rem]")}
                aria-label="Search" data-testid="open-search"
                onClick={() => window.dispatchEvent(new Event("open-command-palette"))}>
                <Search className="h-4 w-4 shrink-0" aria-hidden="true" />
                <span className="hidden truncate sm:inline">Search users, groups, apps…</span>
                <kbd className="ml-auto hidden rounded border bg-background px-1.5 py-0.5 text-[10px] sm:inline">⌘K</kbd>
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
