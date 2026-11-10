import { expect, test } from "@playwright/test";
import { loginAsAdmin } from "./helpers";

test.use({ viewport: { width: 1400, height: 1500 } });

test("the users page shows the status lifecycle; a status filters the list; it collapses", async ({ page }) => {
  await loginAsAdmin(page);
  await page.goto("/admin/users");
  await expect(page.getByTestId("lifecycle-chart")).toBeVisible();
  for (const s of ["staged", "provisioned", "active", "suspended", "password_expired", "recovery", "locked_out", "deprovisioned"]) {
    await expect(page.getByTestId(`lc-${s}`)).toBeVisible();
  }
  await page.getByTestId("lifecycle-chart").screenshot({ path: "/private/tmp/claude-501/-Users-chanderinguva-Development-identityforge/60f081b3-7326-44ec-b03f-28fb73637f2d/scratchpad/lifecycle-light.png" });
  await page.evaluate(() => document.documentElement.classList.add("dark"));
  await page.waitForTimeout(500);
  await page.getByTestId("lifecycle-chart").screenshot({ path: "/private/tmp/claude-501/-Users-chanderinguva-Development-identityforge/60f081b3-7326-44ec-b03f-28fb73637f2d/scratchpad/lifecycle-dark.png" });
  await page.evaluate(() => document.documentElement.classList.remove("dark"));

  // clicking a status filters the list below; clicking it again clears the filter
  await page.getByTestId("lc-suspended").click();
  await expect(page.getByLabel("Filter by status")).toHaveValue("suspended");
  await page.getByTestId("lc-suspended").click();
  await expect(page.getByLabel("Filter by status")).toHaveValue("");

  // keyboard works too
  await page.getByTestId("lc-active").focus();
  await page.keyboard.press("Enter");
  await expect(page.getByLabel("Filter by status")).toHaveValue("active");

  // collapse and expand
  await page.getByTestId("lifecycle-toggle").click();
  await expect(page.getByTestId("lifecycle-chart")).toHaveCount(0);
  await page.getByTestId("lifecycle-toggle").click();
  await expect(page.getByTestId("lifecycle-chart")).toBeVisible();
});
