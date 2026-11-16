import { test } from "@playwright/test";
import { audit, expectNoBlocking, type Finding } from "./a11y";
import { loginAsAdmin } from "./helpers";

// IFORA-42: no serious or critical WCAG 2.1 AA violations on the key admin pages, in both themes.
const PAGES = [
  "/admin/dashboard", "/admin/users", "/admin/groups", "/admin/applications", "/admin/applications/new", "/admin/network-zones",
  "/admin/security-policy", "/admin/audit", "/admin/branding", "/admin/access-requests", "/admin/administrators", "/admin/developers",
];

test.describe("axe: admin pages", () => {
  test.setTimeout(240_000);
  for (const scheme of ["light", "dark"] as const) {
    test(`${scheme} theme`, async ({ page }, info) => {
      await loginAsAdmin(page);
      const all: Finding[] = [];
      for (const path of PAGES) all.push(...(await audit(page, path, scheme, info)));
      expectNoBlocking(all);
    });
  }
});
