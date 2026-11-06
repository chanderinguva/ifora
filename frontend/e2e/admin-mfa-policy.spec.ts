import { expect, test } from "@playwright/test";
import { login, logout } from "./helpers";
import { totp } from "./totp";

// Uses a THROWAWAY admin with no second factor and a one-time enrolment code for it (never the real admin):
//   E2E_POLICY_ADMIN_EMAIL, E2E_POLICY_ADMIN_PASSWORD, E2E_ENROLMENT_CODE
// Needs the stack running with ADMIN_MFA_REQUIRED=true (the default).
const email = process.env.E2E_POLICY_ADMIN_EMAIL ?? "";
const password = process.env.E2E_POLICY_ADMIN_PASSWORD ?? "";
const code = process.env.E2E_ENROLMENT_CODE ?? "";
test.skip(!email || !password || !code, "set E2E_POLICY_ADMIN_EMAIL / _PASSWORD / E2E_ENROLMENT_CODE for a throwaway admin");

test("admin without a second factor: locked to Account settings until a code-gated enrolment", async ({ page }) => {
  await login(page, email, password);
  await expect(page).toHaveURL(/\/settings/);
  await expect(page.getByTestId("mfa-required-banner")).toBeVisible();

  // admin pages bounce back; the API itself refuses
  await page.goto("/admin/users");
  await expect(page).toHaveURL(/\/settings/);
  const status = await page.evaluate(async () => (await fetch("http://localhost:8000/api/v1/admin/users", { credentials: "include" })).status);
  expect(status).toBe(403);

  // the password alone is not enough: a wrong enrolment code is refused
  const card = page.getByTestId("mfa-card");
  await card.getByRole("button", { name: "Set up" }).click();
  await page.locator("#mfa-pw").fill(password);
  await page.locator("#mfa-enrol-code").fill("AAAA-BBBB-CCCC");
  await card.getByRole("button", { name: "Continue" }).click();
  await expect(card.getByRole("status")).toContainText("enrolment code");

  // the right code starts enrolment; confirming it lifts the gate straight away
  await page.locator("#mfa-enrol-code").fill(code);
  await card.getByRole("button", { name: "Continue" }).click();
  const secret = (await page.getByTestId("mfa-secret").innerText()).trim();
  await page.locator("#mfa-enable-code").fill(totp(secret));
  await card.getByRole("button", { name: "Turn on" }).click();
  await expect(page.getByTestId("recovery-codes")).toBeVisible();
  await page.getByRole("button", { name: "I have saved them" }).click();
  await expect(page.getByTestId("mfa-required-banner")).toHaveCount(0);

  await page.goto("/admin/dashboard");
  await expect(page).toHaveURL(/\/admin\/dashboard/);
  await logout(page);
});
