import path from "node:path";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// Unit tests for the console's critical flows (IFORA-59). Playwright (e2e/) covers the browser; these cover logic and components fast.
// Coverage is measured on a named list of critical-flow files, not on all 117 components; the gate is 70% lines on that list.
export default defineConfig({
  plugins: [react()],
  resolve: { alias: { "@": path.resolve(import.meta.dirname, "src") } },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./tests/unit/setup.ts"],
    include: ["tests/unit/**/*.test.{ts,tsx}"],
    restoreMocks: true,
    coverage: {
      provider: "v8",
      reporter: ["text", "text-summary", "json-summary", "html"],
      reportsDirectory: "coverage",
      include: [
        "src/lib/http.ts", "src/lib/stepup.ts", "src/lib/roles.ts", "src/lib/admin-tasks.ts", "src/lib/auth-client.ts",
        "src/components/auth-guard.tsx", "src/components/step-up-dialog.tsx", "src/components/sidebar-nav.tsx",
        "src/components/command-palette.tsx", "src/components/setup-checklist.tsx", "src/components/sessions-card.tsx",
        "src/components/user-role-badges.tsx", "src/components/password-rules.tsx", "src/components/bits.tsx",
        "src/app/login/page.tsx", "src/app/admin/roles/page.tsx", "src/app/admin/dashboard/page.tsx",
      ],
      thresholds: { lines: 70 },
    },
  },
});
