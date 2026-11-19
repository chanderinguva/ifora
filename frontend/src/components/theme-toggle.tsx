"use client";

import { useEffect, useState } from "react";
import { Monitor, Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";
import { cn } from "@/lib/utils";
import { THEME_OPTIONS } from "@/lib/themes";

const ICONS: Record<string, typeof Sun | undefined> = { light: Sun, system: Monitor, dark: Moon };

/** Light / System / Dark plus the extra colour themes (shown as swatches). Remembered by next-themes in localStorage. */
export function ThemeToggle({ className }: { className?: string }) {
  const { theme, setTheme } = useTheme();
  // Rendering the active state only after mount avoids a server/client hydration mismatch.
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  return (
    <div role="radiogroup" aria-label="Colour theme" data-testid="theme-toggle" className={cn("inline-flex flex-wrap rounded-md border p-0.5", className)}>
      {THEME_OPTIONS.map(({ value, label, swatch }) => {
        const Icon = ICONS[value];
        const active = mounted && theme === value;
        return (
          <button
            key={value}
            type="button"
            role="radio"
            aria-checked={active}
            aria-label={`${label} theme`}
            title={`${label} theme`}
            onClick={() => setTheme(value)}
            className={cn(
              "inline-flex h-7 w-7 items-center justify-center rounded-sm text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
              active && "bg-accent text-accent-foreground",
            )}
          >
            {Icon ? (
              <Icon className="h-4 w-4" aria-hidden="true" />
            ) : (
              <span
                aria-hidden="true"
                className="h-4 w-4 rounded-full border border-foreground/30"
                style={{ background: `linear-gradient(135deg, ${swatch?.[0]} 50%, ${swatch?.[1]} 50%)` }}
              />
            )}
          </button>
        );
      })}
    </div>
  );
}
