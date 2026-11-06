"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { ChevronRight } from "lucide-react";
import type { NavGroup } from "./sidebar-nav";
import { cn } from "@/lib/utils";

type Crumb = { label: string; href?: string };

const titleCase = (s: string) => s.replace(/[-_]/g, " ").replace(/^\w/, (c) => c.toUpperCase());

/** Location trail from the URL. Labels come from the nav; numeric ids read as "Details". `/admin` is not a page, so it is skipped. */
export function buildCrumbs(pathname: string, groups: NavGroup[]): Crumb[] {
  const labels = Object.fromEntries(groups.flatMap((g) => g.items).map((i) => [i.href, i.label]));
  const parts = pathname.split("/").filter(Boolean);
  const crumbs: Crumb[] = [];
  let acc = "";
  parts.forEach((part, i) => {
    acc += "/" + part;
    if (part === "admin") return;
    crumbs.push({
      label: labels[acc] ?? (/^\d+$/.test(part) ? "Details" : titleCase(part)),
      href: i < parts.length - 1 ? acc : undefined,
    });
  });
  return crumbs;
}

export function Breadcrumbs({ groups, className }: { groups: NavGroup[]; className?: string }) {
  const crumbs = buildCrumbs(usePathname(), groups);
  if (crumbs.length === 0) return null;
  return (
    <nav aria-label="Breadcrumb" className={cn("min-w-0", className)}>
      <ol className="flex items-center gap-1.5 text-sm text-muted-foreground">
        {crumbs.map((c, i) => (
          <li key={i} className="flex min-w-0 items-center gap-1.5">
            {i > 0 && <ChevronRight className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />}
            {c.href ? (
              <Link href={c.href} className="truncate rounded-sm hover:text-foreground hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                {c.label}
              </Link>
            ) : (
              <span aria-current="page" className="truncate font-medium text-foreground">
                {c.label}
              </span>
            )}
          </li>
        ))}
      </ol>
    </nav>
  );
}
