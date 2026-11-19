/** Selectable colour themes. `value` is the class next-themes puts on <html>; it must match a block in globals.css. */
export type ThemeOption = { value: string; label: string; dark: boolean; swatch?: [string, string] };

export const THEME_OPTIONS: readonly ThemeOption[] = [
  { value: "light", label: "Light", dark: false },
  { value: "system", label: "System", dark: false },
  { value: "dark", label: "Dark", dark: true },
  { value: "sand", label: "Sand", dark: false, swatch: ["#F8F6F1", "#B45309"] },
  { value: "ocean", label: "Ocean", dark: false, swatch: ["#F3F7F9", "#0369A1"] },
  { value: "midnight", label: "Midnight", dark: true, swatch: ["#0D1020", "#60A5FA"] },
  { value: "forest", label: "Forest", dark: true, swatch: ["#0E1511", "#34D399"] },
];

/** Concrete themes passed to next-themes (everything except "system", which it adds itself). */
export const THEME_NAMES = THEME_OPTIONS.filter((t) => t.value !== "system").map((t) => t.value);

/** Class names of the dark-style themes. Keep in sync with the `dark:` variant selector in tailwind.config.ts. */
export const DARK_THEME_CLASSES = THEME_OPTIONS.filter((t) => t.dark).map((t) => t.value);
