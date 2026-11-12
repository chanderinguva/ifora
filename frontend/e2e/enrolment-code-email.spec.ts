import { expect, test, type Page, type Route } from "@playwright/test";

/**
 * Admins who must enrol a first factor can have the one-time enrolment code emailed to them.
 * The server side (delivery, replacement, rate limit, super-admin exclusion) is covered by
 * backend/tests/test_enrollment_code_email.py; here the API is stubbed so the browser flow runs on any stack.
 */

const json = (route: Route, body: unknown, status = 200) =>
  route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

const ADMIN = {
  id: 3, email: "newadmin@example.com", first_name: "New", last_name: "Admin", username: "newadmin",
  is_admin: true, is_super_admin: false, status: "active", profile_attributes: {}, editable_attributes: [],
  mfa_enabled: false, passkey_count: 0, mfa_setup_required: true,
};

async function stub(page: Page, byEmail: boolean) {
  const sent: string[] = [];
  await page.route("**/api/v1/**", (r) => json(r, {}));
  await page.route("**/api/v1/me", (r) => json(r, { authenticated: true, user: { ...ADMIN, enrollment_code_by_email: byEmail }, csrf_token: "csrf" }));
  await page.route("**/api/v1/me/profile", (r) => json(r, { ...ADMIN, enrollment_code_by_email: byEmail }));
  await page.route("**/api/v1/me/passkeys", (r) => json(r, { items: [], count: 0, min_for_policy: 2, require_passkey: false }));
  await page.route("**/api/v1/me/sessions", (r) => json(r, { items: [] }));
  await page.route("**/api/v1/me/activity", (r) => json(r, { items: [] }));
  await page.route("**/api/v1/me/mfa/enrollment-code/email", (r) => { sent.push("email"); return json(r, { success: true }); });
  return sent;
}

test("offers to email the code and confirms it was sent", async ({ page }) => {
  const sent = await stub(page, true);
  await page.goto("/settings");
  await expect(page.getByTestId("mfa-required-banner")).toContainText("we can email one to you");
  await page.getByRole("button", { name: /add a passkey|add passkey|add/i }).first().click();
  await page.getByRole("button", { name: "Email me a code" }).click();
  await expect(page.getByText("Code sent to your email")).toBeVisible();
  await expect(page.getByRole("button", { name: "Send again" })).toBeVisible();
  expect(sent).toEqual(["email"]);
});

test("without the option, the old guidance remains", async ({ page }) => {
  await stub(page, false);
  await page.goto("/settings");
  await expect(page.getByTestId("mfa-required-banner")).toContainText("ask a super admin");
  await expect(page.getByRole("button", { name: "Email me a code" })).toHaveCount(0);
});
