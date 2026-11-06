import { expect, test } from "@playwright/test";
import { USER_PASSWORD, login, loginAsAdmin, logout } from "./helpers";

const run = Date.now().toString(36);
const email = `e2e-${run}@example.com`;
const groupName = `E2E Group ${run}`;

test("admin manages a user and group; the user sees it; admin cleans up", async ({ page }) => {
  // --- admin creates a user and a group, adds the user ---
  await loginAsAdmin(page);
  await page.goto("/admin/users");
  await page.getByRole("button", { name: "New user" }).click();
  await page.locator("#nu-first").fill("E2E");
  await page.locator("#nu-last").fill("Tester");
  await page.locator("#nu-email").fill(email);
  await page.locator("#nu-pw").fill(USER_PASSWORD);
  await page.getByRole("button", { name: "Create user" }).click();
  await page.getByLabel("Search users").fill(email);
  await expect(page.getByTestId("users-table")).toContainText(email);

  await page.goto("/admin/groups");
  await page.getByRole("button", { name: "New group" }).click();
  await page.locator("#g-name").fill(groupName);
  await page.getByRole("button", { name: "Create group" }).click();
  await page.getByRole("link", { name: groupName }).click();
  await page.getByLabel("User to add").selectOption({ label: `E2E Tester (${email})` });
  await page.getByRole("button", { name: "Add", exact: true }).click();
  await expect(page.getByTestId("members-table")).toContainText(email);

  // --- audit log shows what just happened ---
  await page.goto("/admin/audit");
  await page.getByLabel("Filter by action").selectOption("GROUP_MEMBER_ADDED");
  await expect(page.getByTestId("audit-table")).toContainText("GROUP_MEMBER_ADDED");
  await logout(page);

  // --- the new user: lands on user dashboard, sees group, cannot reach admin ---
  await login(page, email, USER_PASSWORD);
  await expect(page).toHaveURL(/\/dashboard$/);
  await expect(page.getByRole("heading", { name: "Hello, E2E" })).toBeVisible();
  await expect(page.getByText(groupName)).toBeVisible();
  await expect(page.getByRole("link", { name: "Users" })).toHaveCount(0);
  await page.goto("/admin/users");
  await expect(page).toHaveURL(/\/dashboard$/);
  const status = await page.evaluate(async () => (await fetch("http://localhost:8000/api/v1/admin/users", { credentials: "include" })).status);
  expect(status).toBe(403);

  // --- self-service profile edit ---
  await page.locator("#pf-title").fill("QA Engineer");
  await page.getByRole("button", { name: "Save profile" }).click();
  await expect(page.getByRole("status")).toContainText("Profile saved");
  await page.reload();
  await expect(page.locator("#pf-title")).toHaveValue("QA Engineer");
  await logout(page);

  // --- admin cleans up (also exercises delete flows) ---
  await loginAsAdmin(page);
  await page.goto("/admin/groups");
  await page.getByRole("link", { name: groupName }).click();
  page.once("dialog", (d) => d.accept());
  await page.getByRole("button", { name: "Delete group" }).click();
  await expect(page).toHaveURL(/\/admin\/groups$/);

  await page.goto("/admin/users");
  await page.getByLabel("Search users").fill(email);
  await page.getByRole("link", { name: "E2E Tester" }).click();
  page.once("dialog", (d) => d.accept());
  await page.getByRole("button", { name: "Delete user" }).click();
  await expect(page).toHaveURL(/\/admin\/users$/);
  await page.getByLabel("Search users").fill(email);
  await expect(page.getByTestId("users-table")).not.toContainText(email);
});
