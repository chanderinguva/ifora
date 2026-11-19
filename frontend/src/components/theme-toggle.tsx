"use client";

import { useEffect, useRef, useState } from "react";
import { Check, Monitor, Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";
import { cn } from "@/lib/utils";
import { THEME_OPTIONS, type ThemeOption } from "@/lib/themes";

const ICONS: Record<string, typeof Sun | undefined> = { light: Sun, system: Monitor, dark: Moon };

function Glyph({ option, className }: { option: ThemeOption; className?: string }) {
  const Icon = ICONS[option.value];
  if (Icon) return <Icon className={cn("h-4 w-4", className)} aria-hidden="true" />;
  return (
    <span
      aria-hidden="true"
      className={cn("h-4 w-4 shrink-0 rounded-full border border-foreground/30", className)}
      style={{ background: `linear-gradient(135deg, ${option.swatch?.[0]} 50%, ${option.swatch?.[1]} 50%)` }}
    />
  );
}

/**
 * One icon button showing the current theme; opens a small list (Light, System, Dark and the colour themes).
 * Remembered by next-themes in localStorage. Escape or an outside click closes it, arrows move between themes.
 */
export function ThemeToggle({ className }: { className?: string }) {
  const { theme, setTheme } = useTheme();
  // Rendering the active state only after mount avoids a server/client hydration mismatch.
  const [mounted, setMounted] = useState(false);
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  useEffect(() => setMounted(true), []);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (root.current && !root.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    const active = root.current?.querySelector<HTMLElement>('[role="radio"][aria-checked="true"]') ?? root.current?.querySelector<HTMLElement>('[role="radio"]');
    active?.focus();
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);

  const current = THEME_OPTIONS.find((t) => t.value === (mounted ? theme : "system")) ?? THEME_OPTIONS[1];

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") {
      setOpen(false);
      trigger.current?.focus();
      return;
    }
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
    e.preventDefault();
    const items = Array.from(root.current?.querySelectorAll<HTMLElement>('[role="radio"]') ?? []);
    const i = items.indexOf(document.activeElement as HTMLElement);
    const next = e.key === "ArrowDown" ? (i + 1) % items.length : (i - 1 + items.length) % items.length;
    items[next]?.focus();
  };

  return (
    <div ref={root} data-testid="theme-toggle" className={cn("relative", className)} onKeyDown={onKeyDown}>
      <button
        ref={trigger}
        type="button"
        aria-haspopup="true"
        aria-expanded={open}
        aria-label={`Colour theme: ${current.label}`}
        title={`Colour theme: ${current.label}`}
        onClick={() => setOpen((o) => !o)}
        className="inline-flex h-8 w-8 items-center justify-center rounded-md border text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <Glyph option={current} />
      </button>
      {open && (
        <div
          role="radiogroup"
          aria-label="Colour theme"
          className="absolute right-0 top-full z-30 mt-1 w-40 rounded-lg border bg-popover p-1 text-popover-foreground shadow-md dark:shadow-none"
        >
          {THEME_OPTIONS.map((option) => {
            const active = mounted && theme === option.value;
            return (
              <button
                key={option.value}
                type="button"
                role="radio"
                aria-checked={active}
                aria-label={`${option.label} theme`}
                onClick={() => {
                  setTheme(option.value);
                  setOpen(false);
                  trigger.current?.focus();
                }}
                className={cn(
                  "flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                  active && "bg-accent font-medium",
                )}
              >
                <Glyph option={option} className="text-muted-foreground" />
                <span className="flex-1">{option.label}</span>
                {active && <Check className="h-3.5 w-3.5" aria-hidden="true" />}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
