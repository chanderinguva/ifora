"use client";

import { ExternalLink, LayoutGrid, ShieldCheck } from "lucide-react";
import { cn } from "@/lib/utils";

/** Navigation only: never changes the shared cookie session's role mode. */
export function DashboardShortcut({ personal, collapsed = false }: { personal: boolean; collapsed?: boolean }) {
  const label = personal ? "Admin console" : "End-user dashboard";
  const Icon = personal ? ShieldCheck : LayoutGrid;
  return (
    <div className="shrink-0 border-t p-3">
      <a href={personal ? "/admin/dashboard" : "/dashboard"} target="_blank" rel="noopener noreferrer"
        data-testid="dashboard-shortcut" aria-label={label + " (opens in a new tab)"} title={label + " (opens in a new tab)"}
        className={cn("flex min-h-10 items-center rounded-md text-sm font-medium text-muted-foreground hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
          collapsed ? "justify-center" : "gap-3 px-3")}>
        <Icon className="h-4 w-4 shrink-0" aria-hidden />
        {!collapsed && <><span className="min-w-0 flex-1">{label}</span><ExternalLink className="h-3.5 w-3.5 shrink-0" aria-hidden /></>}
      </a>
    </div>
  );
}
