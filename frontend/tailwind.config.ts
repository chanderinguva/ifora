import type { Config } from "tailwindcss";

export default {
  darkMode: ["class"],
  content: ["./src/**/*.{ts,tsx}", "./pages/**/*.{ts,tsx}", "./src/components/**/*.{ts,tsx}"],
  plugins: [],
  theme: {
  extend: {
    fontFamily: {
      sans: ["var(--font-inter)", "ui-sans-serif", "system-ui", "sans-serif"],
      brand: ["var(--font-lora)", "Georgia", "serif"],
      mono: ["var(--font-mono)", "ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
    },
    colors: {
      border: "hsl(var(--border))",
      input: "hsl(var(--input))",
      ring: "hsl(var(--ring))",
      background: "hsl(var(--background))",
      foreground: "hsl(var(--foreground))",
      primary: {
        DEFAULT: "hsl(var(--primary))",
        foreground: "hsl(var(--primary-foreground))",
      },
      secondary: {
        DEFAULT: "hsl(var(--secondary))",
        foreground: "hsl(var(--secondary-foreground))",
      },
      destructive: {
        DEFAULT: "hsl(var(--destructive))",
        foreground: "hsl(var(--destructive-foreground))",
      },
      muted: {
        DEFAULT: "hsl(var(--muted))",
        foreground: "hsl(var(--muted-foreground))",
      },
      card: {
        DEFAULT: "hsl(var(--card))",
        foreground: "hsl(var(--card-foreground))",
      },
      popover: {
        DEFAULT: "hsl(var(--popover))",
        foreground: "hsl(var(--popover-foreground))",
      },
      accent: {
        DEFAULT: "hsl(var(--accent))",
        foreground: "hsl(var(--accent-foreground))",
      },
      selected: {
        DEFAULT: "hsl(var(--selected))",
        foreground: "hsl(var(--selected-foreground))",
      },
      good: "hsl(var(--good))",
      warn: "hsl(var(--warn))",
      bad: "hsl(var(--bad))",
    },
    transitionTimingFunction: { DEFAULT: "cubic-bezier(0.2, 0, 0, 1)" },
    transitionDuration: { DEFAULT: "150ms" },
    borderRadius: {
      lg: "var(--radius)",
      md: "calc(var(--radius) - 2px)",
      sm: "calc(var(--radius) - 4px)",
    },
  },
},
} satisfies Config;