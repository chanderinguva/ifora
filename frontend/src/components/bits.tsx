"use client";

import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { formatDateTime } from "@/lib/display";

export const fieldClass =
  "flex h-9 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background transition-colors placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

/** Identifiers, versions, timestamps and counts: mono, muted, aligned. */
export const mono = "font-mono text-[13px] tabular-nums text-muted-foreground";

/** A status as a small dot plus text. Colour carries the meaning, the word carries it for everyone else. */
export function Badge({
  children,
  tone = "neutral",
}: {
  children: React.ReactNode;
  tone?: "neutral" | "good" | "bad" | "info";
}) {
  const dot = {
    neutral: "bg-muted-foreground/50",
    good: "bg-good",
    bad: "bg-bad",
    info: "bg-primary",
  };
  return (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap text-xs font-medium text-foreground/80">
      <span aria-hidden="true" className={cn("h-1.5 w-1.5 shrink-0 rounded-full", dot[tone])} />
      {children}
    </span>
  );
}

export function PageHeader({ title, children }: { title: string; children?: React.ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
      <h1 className="text-2xl font-medium tracking-tight">{title}</h1>
      <div className="flex items-center gap-2">{children}</div>
    </div>
  );
}

export function Pager({
  page,
  pageSize,
  total,
  onPage,
}: {
  page: number;
  pageSize: number;
  total: number;
  onPage: (p: number) => void;
}) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  return (
    <div className="mt-4 flex items-center justify-between text-sm text-muted-foreground">
      <span className="tabular-nums">
        {total} result{total === 1 ? "" : "s"}
      </span>
      <div className="flex items-center gap-2">
        <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => onPage(page - 1)}>
          Previous
        </Button>
        <span>
          Page {page} of {pages}
        </span>
        <Button variant="outline" size="sm" disabled={page >= pages} onClick={() => onPage(page + 1)}>
          Next
        </Button>
      </div>
    </div>
  );
}

export const th = "px-4 py-2.5 text-left text-xs font-medium text-muted-foreground";
export const td = "px-4 py-3 text-sm";
/** Table row: hover is a surface step, selection is the indigo tint, keyboard focus is an inset ring. */
export const tr = "border-b last:border-0 transition-colors hover:bg-accent/60 focus-within:bg-accent/60 data-[selected=true]:bg-selected";

export function fmt(ts: string | null | undefined) {
  return ts ? formatDateTime(ts) : "—";
}
