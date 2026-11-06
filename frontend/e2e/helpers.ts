import { expect, type Page } from "@playwright/test";

export const ADMIN_EMAIL = process.env.ADMIN_EMAIL ?? "admin@inguva.dev";
export const ADMIN_PASSWORD = process.env.ADMIN_PASSWORD ?? "";
export const USER_PASSWORD = "E2eTempPassw0rd!" + Math.floor(Math.random() * 1000);

export async function login(page: Page, email: string, password: string) {
  await page.goto("/login");
  await page.locator("#email").fill(email);
  await page.locator("#password").fill(password);
  await page.getByRole("button", { name: "Sign In", exact: true }).click();
}

export async function loginAsAdmin(page: Page) {
  expect(ADMIN_PASSWORD, "ADMIN_PASSWORD must be set (source ../.env)").not.toBe("");
  await login(page, ADMIN_EMAIL, ADMIN_PASSWORD);
  await expect(page).toHaveURL(/\/admin\/dashboard/);
}

export async function logout(page: Page) {
  await page.getByTestId("user-menu").click();
  await page.getByRole("menuitem", { name: "Log out" }).click();
  await expect(page).toHaveURL(/\/login/);
}
