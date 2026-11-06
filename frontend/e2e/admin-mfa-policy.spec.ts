import { expect, test } from "@playwright/test";
import { ADMIN_EMAIL, ADMIN_PASSWORD, login, logout } from "./helpers";

// Needs the stack started with ADMIN_MFA_REQUIRED=true and an admin that has no second factor.
// The rest of the suite signs in as that admin, so run it with the policy off:
//   E2E_ADMIN_MFA_POLICY=on npx playwright test admin-mfa-policy
test.skip(process.env.E2E_ADMIN_MFA_POLICY !== "on", "set E2E_ADMIN_MFA_POLICY=on against a stack with the policy enabled");

test("an admin without a second factor is sent to Account settings and locked out of the admin API", async ({ page }) => {
  await login(page, ADMIN_EMAIL, ADMIN_PASSWORD);
  await expect(page).toHaveURL(/\/settings/);
  await expect(page.getByTestId("mfa-required-banner")).toBeVisible();
  await expect(page.getByTestId("passkey-card")).toBeVisible();

  // admin pages bounce back; the API itself refuses
  await page.goto("/admin/users");
  await expect(page).toHaveURL(/\/settings/);
  const status = await page.evaluate(async () => (await fetch("http://localhost:8000/api/v1/admin/users", { credentials: "include" })).status);
  expect(status).toBe(403);

  await logout(page);
});
