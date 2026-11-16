import { expect, test } from "@playwright/test";
import { audit, expectNoBlocking, type Finding } from "./a11y";
import { loginAsAdmin } from "./helpers";

// IFORA-42: the sign-in page (signed out) and the end-user pages (signed in) in both themes.
test.describe("axe: end-user pages", () => {
  test.setTimeout(240_000);
  for (const scheme of ["light", "dark"] as const) {
    test(`sign-in page, ${scheme} theme`, async ({ page }, info) => {
      const all: Finding[] = [];
      for (const path of ["/login", "/forgot-password"]) all.push(...(await audit(page, path, scheme, info)));
      expectNoBlocking(all);
    });
    test(`signed-in pages, ${scheme} theme`, async ({ page }, info) => {
      await loginAsAdmin(page);
      const all: Finding[] = [];
      for (const path of ["/dashboard", "/apps/request", "/settings"]) all.push(...(await audit(page, path, scheme, info)));
      expectNoBlocking(all);
      expect(page.url()).not.toContain("/login");
    });
  }
});
