import { expect, test } from "@playwright/test";
import { USER_PASSWORD, login, loginAsAdmin, logout } from "./helpers";
import { totp } from "./totp";

const run = Date.now().toString(36);
const email = `e2e-mfa-${run}@example.com`;

test("user enrols TOTP, signs in with it and with a recovery code, then turns it off", async ({ page }) => {
  // admin provisions the user
  await loginAsAdmin(page);
  await page.goto("/admin/users");
  await page.getByRole("button", { name: "New user" }).click();
  await page.locator("#nu-first").fill("MFA");
  await page.locator("#nu-last").fill("Tester");
  await page.locator("#nu-email").fill(email);
  await page.locator("#nu-pw").fill(USER_PASSWORD);
  await page.getByRole("button", { name: "Create user" }).click();
  await page.getByLabel("Search users").fill(email);
  await expect(page.getByTestId("users-table")).toContainText(email);
  await logout(page);

  // enrol
  await login(page, email, USER_PASSWORD);
  await expect(page).toHaveURL(/\/dashboard$/);
  await page.goto("/settings");
  const card = page.getByTestId("mfa-card");
  await card.getByRole("button", { name: "Set up" }).click();
  await page.locator("#mfa-pw").fill("WrongPassw0rd!!");
  await card.getByRole("button", { name: "Continue" }).click();
  await expect(card.getByRole("status")).toContainText("Password is incorrect");
  await page.locator("#mfa-pw").fill(USER_PASSWORD);
  await card.getByRole("button", { name: "Continue" }).click();
  const secret = (await page.getByTestId("mfa-secret").innerText()).trim();
  expect(secret).toMatch(/^[A-Z2-7]{32}$/);
  await expect(card.locator("svg")).toBeVisible(); // QR code
  await page.locator("#mfa-enable-code").fill("000000");
  await card.getByRole("button", { name: "Turn on" }).click();
  await expect(card.getByRole("status")).toContainText("Invalid code");
  await page.locator("#mfa-enable-code").fill(totp(secret));
  await card.getByRole("button", { name: "Turn on" }).click();
  await expect(page.getByTestId("recovery-codes")).toBeVisible();
  const codes = (await page.getByTestId("recovery-codes").locator("li").allInnerTexts()).map((s) => s.trim());
  expect(codes).toHaveLength(10);
  await page.getByRole("button", { name: "I have saved them" }).click();
  await logout(page);

  // password alone is not enough
  await login(page, email, USER_PASSWORD);
  await expect(page.getByRole("heading", { name: "Two-step verification" })).toBeVisible();
  await expect(page).toHaveURL(/\/login/);
  await page.goto("/dashboard");
  await expect(page).toHaveURL(/\/login/); // still no session

  // wrong code, then right code (next 30 s step: the enrolment code's step is already used)
  await login(page, email, USER_PASSWORD);
  await page.locator("#mfa-code").fill("000000");
  await page.getByRole("button", { name: "Verify" }).click();
  await expect(page.getByText("Invalid or expired code")).toBeVisible();
  await page.locator("#mfa-code").fill(totp(secret, 30));
  await page.getByRole("button", { name: "Verify" }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
  await logout(page);

  // recovery code works once
  await login(page, email, USER_PASSWORD);
  await page.locator("#mfa-code").fill(codes[0]);
  await page.getByRole("button", { name: "Verify" }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
  await page.goto("/settings");
  await expect(page.getByTestId("mfa-card")).toContainText("9 recovery codes remaining");
  await logout(page);
  await login(page, email, USER_PASSWORD);
  await page.locator("#mfa-code").fill(codes[0]);
  await page.getByRole("button", { name: "Verify" }).click();
  await expect(page.getByText("Invalid or expired code")).toBeVisible();

  // turn it off (password + a fresh recovery code)
  await page.locator("#mfa-code").fill(codes[1]);
  await page.getByRole("button", { name: "Verify" }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
  await page.goto("/settings");
  const card2 = page.getByTestId("mfa-card");
  await card2.getByRole("button", { name: "Turn off" }).click();
  await page.locator("#mfa-pw2").fill(USER_PASSWORD);
  await page.locator("#mfa-code2").fill(codes[2]);
  await card2.getByRole("button", { name: "Turn off" }).last().click();
  await expect(card2.getByRole("status")).toContainText("Two-step verification is off");
  await logout(page);
  await login(page, email, USER_PASSWORD);
  await expect(page).toHaveURL(/\/dashboard$/); // no second step any more
  await logout(page);

  // cleanup
  await loginAsAdmin(page);
  await page.goto("/admin/users");
  await page.getByLabel("Search users").fill(email);
  await page.getByRole("link", { name: "MFA Tester" }).click();
  page.once("dialog", (d) => d.accept());
  await page.getByRole("button", { name: "Delete user" }).click();
  await expect(page).toHaveURL(/\/admin\/users$/);
});
