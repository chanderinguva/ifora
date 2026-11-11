"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

export type NavItem = { href: string; label: string; icon: LucideIcon; area?: string };
/** A labelled group of related destinations (the label is optional for the first, primary group). */
export type NavGroup = { label?: string; items: NavItem[] };

/**
 * Sidebar navigation. Used by the desktop rail (expanded or collapsed) and the mobile drawer.
 * Collapsed: icons only, with the label kept as the accessible name and shown as a tooltip on hover AND keyboard focus.
 */
export function SidebarNav({
  groups,
  collapsed = false,
  onNavigate,
}: {
  groups: NavGroup[];
  collapsed?: boolean;
  onNavigate?: () => void;
}) {
  const pathname = usePathname();
  return (
    <nav aria-label="Main" className={cn("flex-1 p-3", collapsed ? "overflow-visible" : "overflow-y-auto")}>
      {groups.map((group, gi) => (
        <div key={gi} className={cn(gi > 0 && "mt-6")}>
          {group.label &&
            (collapsed ? (
              <div className="mx-2 mb-2 border-t" aria-hidden="true" />
            ) : (
              <div className="mb-2 px-3 text-xs font-medium text-muted-foreground" aria-hidden="true">
                {group.label}
              </div>
            ))}
          <ul className="space-y-0.5" aria-label={group.label}>
            {group.items.map(({ href, label, icon: Icon }) => {
              const active = pathname === href || pathname.startsWith(href + "/");
              return (
                <li key={href}>
                  <Link
                    href={href}
                    onClick={onNavigate}
                    aria-current={active ? "page" : undefined}
                    aria-label={collapsed ? label : undefined}
                    className={cn(
                      "group relative flex h-9 items-center rounded-md text-sm font-medium outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring",
                      collapsed ? "justify-center px-0" : "gap-3 px-3",
                      active ? "bg-accent text-foreground ring-1 ring-inset ring-border" : "text-muted-foreground hover:bg-accent/60 hover:text-foreground",
                    )}
                  >
                    {active && !collapsed && <span aria-hidden="true" className="absolute left-1 top-1/2 h-1.5 w-1.5 -translate-y-1/2 rounded-full bg-primary" />}
                    <Icon className="h-4 w-4 shrink-0" strokeWidth={1.5} aria-hidden="true" />
                    {!collapsed && <span className="truncate">{label}</span>}
                    {collapsed && (
                      <span
                        aria-hidden="true"
                        className="pointer-events-none absolute left-full z-30 ml-3 whitespace-nowrap rounded-md border bg-popover px-2 py-1 text-xs font-medium text-popover-foreground opacity-0 shadow-md transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100"
                      >
                        {label}
                      </span>
                    )}
                  </Link>
                </li>
              );
            })}
          </ul>
        </div>
      ))}
    </nav>
  );
}
