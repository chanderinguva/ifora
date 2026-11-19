import { readFileSync } from "node:fs";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const theme = vi.hoisted(() => ({ setTheme: vi.fn(), current: "light" }));
vi.mock("next-themes", () => ({ useTheme: () => ({ theme: theme.current, setTheme: theme.setTheme }) }));

import { ThemeToggle } from "@/components/theme-toggle";
import { DARK_THEME_CLASSES, THEME_NAMES, THEME_OPTIONS } from "@/lib/themes";

beforeEach(() => {
  theme.setTheme.mockReset();
  theme.current = "light";
});

describe("theme list", () => {
  it("keeps light, system and dark and adds extra themes", () => {
    const values = THEME_OPTIONS.map((t) => t.value);
    expect(values.slice(0, 3)).toEqual(["light", "system", "dark"]);
    expect(values.length).toBeGreaterThan(3);
    expect(new Set(values).size).toBe(values.length);
    expect(THEME_NAMES).not.toContain("system");
  });

  it("every theme has a palette block in globals.css and dark-style themes are in the tailwind dark variant", () => {
    const css = readFileSync("src/app/globals.css", "utf8");
    const tw = readFileSync("tailwind.config.ts", "utf8");
    for (const t of THEME_OPTIONS.filter((o) => o.value !== "system" && o.value !== "light")) {
      expect(css, t.value).toMatch(new RegExp(`\\n  \\.${t.value} \\{`));
    }
    for (const c of DARK_THEME_CLASSES) {
      expect(tw, c).toContain(`.${c} *`);
      expect(css, c).toMatch(new RegExp(`\\.${c}[,\\s][^{]*\\{\\s*color-scheme: dark`));
    }
  });
});

describe("ThemeToggle", () => {
  it("lists every theme as a radio and selects one with the keyboard", async () => {
    const user = userEvent.setup();
    render(<ThemeToggle />);
    const radios = await screen.findAllByRole("radio");
    expect(radios).toHaveLength(THEME_OPTIONS.length);
    await user.click(screen.getByRole("radio", { name: "Midnight theme" }));
    expect(theme.setTheme).toHaveBeenCalledWith("midnight");
    screen.getByRole("radio", { name: "Forest theme" }).focus();
    await user.keyboard("{Enter}");
    expect(theme.setTheme).toHaveBeenLastCalledWith("forest");
  });

  it("marks the active theme", async () => {
    theme.current = "sand";
    render(<ThemeToggle />);
    expect(await screen.findByRole("radio", { name: "Sand theme", checked: true })).toBeTruthy();
  });
});
