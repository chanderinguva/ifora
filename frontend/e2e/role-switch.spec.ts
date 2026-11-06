import { expect, test } from "@playwright/test";
import { login, logout } from "./helpers";

// Uses a THROWAWAY admin (never the real one): E2E_ROLE_ADMIN_EMAIL, E2E_ROLE_ADMIN_PASSWORD.
// The backend must run with ADMIN_MFA_REQUIRED=false for this account, which has no second factor.
const email = process.env.E2E_ROLE_ADMIN_EMAIL ?? "";
const password = process.env.E2E_ROLE_ADMIN_PASSWORD ?? "";
test.skip(!email || !password, "set E2E_ROLE_ADMIN_EMAIL / E2E_ROLE_ADMIN_PASSWORD for a throwaway admin");

const adminApi = (page: import("@playwright/test").Page) =>
  page.evaluate(async () => (await fetch("http://localhost:8000/api/v1/admin/users", { credentials: "include" })).status);

test("an admin works as a normal user, loses admin powers server-side, and steps back up with a password", async ({ page }) => {
  await login(page, email, password);
  await expect(page).toHaveURL(/\/admin\/dashboard/);
  const nav = page.getByRole("navigation", { name: "Main" });
  await expect(nav.getByRole("link", { name: "Users" })).toBeVisible();
  expect(await adminApi(page)).toBe(200);

  // switch to user view: no password needed, it only lowers privilege
  await page.getByTestId("user-menu").click();
  await page.getByTestId("switch-to-user").click();
  await expect(page).toHaveURL(/\/dashboard$/);
  await expect(page.getByTestId("user-view-banner")).toBeVisible();
  await expect(page.getByTestId("user-menu")).toContainText("user view");
  await expect(nav.getByRole("link", { name: "Users" })).toHaveCount(0);
  await expect(page.getByRole("link", { name: "Go to administration" })).toHaveCount(0);

  // admin pages bounce, and the API itself refuses
  await page.goto("/admin/users");
  await expect(page).toHaveURL(/\/dashboard$/);
  expect(await adminApi(page)).toBe(403);
  await page.goto("/settings"); // self-service still works
  await expect(page.getByRole("heading", { name: "Account settings" })).toBeVisible();

  // step back up: a wrong password is refused, the right one restores admin view
  await page.getByTestId("user-menu").click();
  await page.getByTestId("switch-to-admin").click();
  const stepUp = page.getByRole("form", { name: "Confirm your password" });
  await page.locator("#role-pw").fill("WrongPassw0rd!!");
  await stepUp.getByRole("button", { name: "Switch to admin view" }).click();
  await expect(page.getByTestId("role-error")).toContainText("Password is incorrect");
  expect(await adminApi(page)).toBe(403);
  await page.locator("#role-pw").fill(password);
  await stepUp.getByRole("button", { name: "Switch to admin view" }).click();
  await expect(page).toHaveURL(/\/admin\/dashboard/);
  await expect(page.getByTestId("user-view-banner")).toHaveCount(0);
  expect(await adminApi(page)).toBe(200);
  await logout(page);
});
