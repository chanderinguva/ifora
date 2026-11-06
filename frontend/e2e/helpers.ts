import { expect, type Page } from "@playwright/test";
import { totp } from "./totp";

export const ADMIN_EMAIL = process.env.ADMIN_EMAIL ?? "admin@inguva.dev";
export const ADMIN_PASSWORD = process.env.ADMIN_PASSWORD ?? "";
export const USER_PASSWORD = "E2eTempPassw0rd!" + Math.floor(Math.random() * 1000);

export async function login(page: Page, email: string, password: string) {
  await page.goto("/login");
  await page.locator("#email").fill(email);
  await page.locator("#password").fill(password);
  await page.getByRole("button", { name: "Sign In", exact: true }).click();
}

// Base32 secret of the admin's authenticator app, only needed once that admin has enrolled TOTP.
export const ADMIN_TOTP_SECRET = process.env.ADMIN_TOTP_SECRET ?? "";
let lastTotpStep = -1;

/** Answer the second step if the account asks for it. A code is single-use, so wait for a fresh 30 s step. */
async function passSecondStep(page: Page) {
  const field = page.locator("#mfa-code");
  const asked = await field.waitFor({ state: "visible", timeout: 4000 }).then(() => true, () => false);
  if (!asked) return;
  expect(ADMIN_TOTP_SECRET, "the admin has MFA on: set ADMIN_TOTP_SECRET (base32) in .env").not.toBe("");
  let step = Math.floor(Date.now() / 30000);
  if (step <= lastTotpStep) {
    await page.waitForTimeout((lastTotpStep + 1) * 30000 - Date.now() + 500);
    step = lastTotpStep + 1;
  }
  lastTotpStep = step;
  await field.fill(totp(ADMIN_TOTP_SECRET));
  await page.getByRole("button", { name: "Verify" }).click();
}

export async function loginAsAdmin(page: Page) {
  expect(ADMIN_PASSWORD, "ADMIN_PASSWORD must be set (source ../.env)").not.toBe("");
  await login(page, ADMIN_EMAIL, ADMIN_PASSWORD);
  await passSecondStep(page);
  await expect(page).toHaveURL(/\/admin\/dashboard/);
}

export async function logout(page: Page) {
  await page.getByTestId("user-menu").click();
  await page.getByRole("menuitem", { name: "Log out" }).click();
  await expect(page).toHaveURL(/\/login/);
}
