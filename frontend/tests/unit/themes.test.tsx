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
  it("is one button until opened, then lists every theme and selects one with the keyboard", async () => {
    const user = userEvent.setup();
    render(<ThemeToggle />);
    expect(screen.queryAllByRole("radio")).toHaveLength(0);
    await user.click(await screen.findByRole("button", { name: /^Colour theme/ }));
    expect(screen.getAllByRole("radio")).toHaveLength(THEME_OPTIONS.length);
    await user.click(screen.getByRole("radio", { name: "Midnight theme" }));
    expect(theme.setTheme).toHaveBeenCalledWith("midnight");
    expect(screen.queryAllByRole("radio")).toHaveLength(0); // closes after choosing

    await user.click(screen.getByRole("button", { name: /^Colour theme/ }));
    screen.getByRole("radio", { name: "Forest theme" }).focus();
    await user.keyboard("{Enter}");
    expect(theme.setTheme).toHaveBeenLastCalledWith("forest");
  });

  it("Escape closes and the trigger names and marks the active theme", async () => {
    const user = userEvent.setup();
    theme.current = "sand";
    render(<ThemeToggle />);
    const trigger = await screen.findByRole("button", { name: "Colour theme: Sand" });
    await user.click(trigger);
    expect(screen.getByRole("radio", { name: "Sand theme", checked: true })).toBeTruthy();
    await user.keyboard("{Escape}");
    expect(screen.queryAllByRole("radio")).toHaveLength(0);
  });
});
