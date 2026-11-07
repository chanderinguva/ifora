"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Search } from "lucide-react";
import { http } from "@/lib/http";
import type { NavGroup } from "./sidebar-nav";

type Hit = { kind: string; id?: number; title: string; subtitle?: string; href: string };

/** Cmd/Ctrl+K: jump to any admin page, or search users, groups, applications, recipes and group rules. */
export function CommandPalette({ nav }: { nav: NavGroup[] }) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [found, setFound] = useState<Hit[]>([]);
  const [active, setActive] = useState(0);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); setOpen((o) => !o); }
      else if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    const onOpen = () => setOpen(true);
    window.addEventListener("open-command-palette", onOpen);
    return () => { window.removeEventListener("keydown", onKey); window.removeEventListener("open-command-palette", onOpen); };
  }, []);

  useEffect(() => { if (open) { setQ(""); setFound([]); setActive(0); setTimeout(() => input.current?.focus(), 0); } }, [open]);

  useEffect(() => {
    const term = q.trim();
    if (term.length < 2) { setFound([]); return; }
    let alive = true;
    const t = setTimeout(() => {
      http<{ results: Hit[] }>(`/admin/search?q=${encodeURIComponent(term)}`).then((r) => alive && setFound(r.results)).catch(() => alive && setFound([]));
    }, 150);
    return () => { alive = false; clearTimeout(t); };
  }, [q]);

  const pages: Hit[] = useMemo(
    () => nav.flatMap((g) => g.items).filter((i) => !q.trim() || i.label.toLowerCase().includes(q.trim().toLowerCase())).map((i) => ({ kind: "page", title: i.label, href: i.href })),
    [nav, q],
  );
  const all = [...pages, ...found];
  useEffect(() => setActive(0), [q, found.length]);

  const go = (h?: Hit) => { if (h) { setOpen(false); router.push(h.href); } };

  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/40 px-4 pt-[15vh]" role="dialog" aria-modal="true" aria-label="Search" onMouseDown={(e) => { if (e.target === e.currentTarget) setOpen(false); }}>
      <div className="w-full max-w-lg overflow-hidden rounded-lg border bg-background shadow-xl" data-testid="command-palette">
        <div className="flex items-center gap-2 border-b px-3">
          <Search className="h-4 w-4 text-muted-foreground" />
          <input
            ref={input} value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search users, groups, applications, recipes… or jump to a page"
            className="h-12 w-full bg-transparent text-sm outline-none" aria-label="Search"
            onKeyDown={(e) => {
              if (e.key === "ArrowDown") { e.preventDefault(); setActive((a) => Math.min(a + 1, all.length - 1)); }
              else if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)); }
              else if (e.key === "Enter") go(all[active]);
            }}
          />
        </div>
        <ul className="max-h-80 overflow-y-auto py-1" role="listbox">
          {all.map((h, i) => (
            <li key={`${h.kind}-${h.id ?? h.href}-${i}`} role="option" aria-selected={i === active}
              className={"flex cursor-pointer items-center justify-between gap-3 px-3 py-2 text-sm " + (i === active ? "bg-accent" : "")}
              onMouseEnter={() => setActive(i)} onClick={() => go(h)}>
              <span className="truncate">{h.title}{h.subtitle && <span className="ml-2 text-xs text-muted-foreground">{h.subtitle}</span>}</span>
              <span className="shrink-0 rounded bg-muted px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-muted-foreground">{h.kind}</span>
            </li>
          ))}
          {all.length === 0 && <li className="px-3 py-6 text-center text-sm text-muted-foreground">No matches</li>}
        </ul>
        <div className="border-t px-3 py-1.5 text-[11px] text-muted-foreground">↑↓ to move · Enter to open · Esc to close</div>
      </div>
    </div>
  );
}
