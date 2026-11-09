import { expect, test } from "@playwright/test";
import { USER_PASSWORD, login, loginAsAdmin, logout } from "./helpers";

test("a super admin gives an administrator the report role; that admin sees only what the role allows", async ({ page }) => {
  await loginAsAdmin(page);
  const tag = Date.now();
  const email = `report.admin.${tag}@example.com`;

  // create an administrator and assign the role
  await page.goto("/admin/users");
  await page.getByRole("button", { name: "New user" }).click();
  await page.locator("#nu-first").fill("Report");
  await page.locator("#nu-last").fill(`Admin${tag}`);
  await page.locator("#nu-email").fill(email);
  await page.getByLabel("I will set a password").check();
  await page.locator("#nu-pw").fill(USER_PASSWORD);
  await page.getByLabel(/administrator/i).first().check();
  await page.getByRole("button", { name: "Create user" }).click();
  await page.getByLabel("Search users").fill(email);
  await page.getByRole("link", { name: /Report Admin/ }).first().click();
  await expect(page.getByTestId("admin-roles")).toContainText("full organization-administrator access");
  await page.getByTestId("role-report_admin").check();
  await page.getByTestId("roles-save").click();
  await expect(page.getByText(/Roles saved/)).toBeVisible();
  await logout(page);

  // the report admin: sees System log and Users, not Applications or Groups; the server also refuses
  await login(page, email, USER_PASSWORD);
  await expect(page).toHaveURL(/\/admin\/dashboard/);
  const nav = page.getByRole("navigation", { name: "Main" });
  await expect(nav.getByRole("link", { name: "System log" })).toBeVisible();
  await expect(nav.getByRole("link", { name: "Applications", exact: true })).toHaveCount(0);
  await expect(nav.getByRole("link", { name: "Groups", exact: true })).toHaveCount(0);
  const denied = await page.evaluate(async () => (await fetch("http://localhost:8000/api/v1/admin/applications", { credentials: "include" })).status);
  expect(denied).toBe(403);
  await logout(page);

  // clean up: delete the administrator
  await loginAsAdmin(page);
  await page.goto("/admin/users");
  await page.getByLabel("Search users").fill(email);
  await page.getByRole("link", { name: /Report Admin/ }).first().click();
  page.once("dialog", (d) => d.accept());
  await page.getByRole("button", { name: "Delete user" }).click();
  await expect(page).toHaveURL(/\/admin\/users$/);
});
