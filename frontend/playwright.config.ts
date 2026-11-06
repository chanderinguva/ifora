import { defineConfig } from "@playwright/test";

/**
 * Browser tests run against the live Docker stack (frontend :3000, API :8000).
 * Credentials come from the environment, never from source:
 *   set -a; . ../.env; set +a; npx playwright test
 * Uses the system Chrome (no browser download). Override with E2E_CHANNEL="" to use bundled Chromium.
 */
export default defineConfig({
  testDir: "./e2e",
  workers: 1,
  timeout: 60_000,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000",
    channel: process.env.E2E_CHANNEL ?? "chrome",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
});
