import { expect, test } from "@playwright/test";
import { USER_PASSWORD, loginAsAdmin } from "./helpers";

test("bulk-suspend and deactivate two users, then check the Applications and Activity tabs", async ({ page }) => {
  await loginAsAdmin(page);
  const tag = Date.now();
  const emails = [`bulk1.${tag}@example.com`, `bulk2.${tag}@example.com`];
  for (const email of emails) {
    await page.goto("/admin/users");
    await page.getByRole("button", { name: "New user" }).click();
    await page.locator("#nu-first").fill("Bulk");
    await page.locator("#nu-last").fill(`T${tag}`);
    await page.locator("#nu-email").fill(email);
    await page.getByLabel("I will set a password").check();
    await page.locator("#nu-pw").fill(USER_PASSWORD);
    await page.getByRole("button", { name: "Create user" }).click();
    await expect(page.getByLabel("Search users")).toBeVisible();
  }

  await page.goto("/admin/users");
  await page.getByLabel("Search users").fill(`T${tag}`);
  for (const email of emails) await page.getByLabel(`Select ${email}`).check();
  await expect(page.getByTestId("bulk-bar")).toContainText("2 selected");
  await page.getByTestId("bulk-suspend").click();
  await expect(page.getByTestId("bulk-note")).toContainText("2 users updated");
  await expect(page.getByTestId("users-table")).toContainText("suspended");

  // detail tabs
  await page.getByRole("link", { name: /Bulk T/ }).first().click();
  await page.getByTestId("utab-applications").click();
  await expect(page.getByTestId("user-apps")).toContainText("no applications");
  await page.getByTestId("utab-activity").click();
  await expect(page.getByTestId("user-activity")).toContainText(/user status changed|user created/i);
  await page.getByTestId("utab-profile").click();

  // deactivate both in bulk, then delete each from its detail page so nothing is left behind
  await page.goto("/admin/users");
  await page.getByLabel("Search users").fill(`T${tag}`);
  for (const email of emails) await page.getByLabel(`Select ${email}`).check();
  page.once("dialog", (d) => d.accept());
  await page.getByTestId("bulk-deactivate").click();
  await expect(page.getByTestId("bulk-note")).toContainText("2 users updated");
  for (const email of emails) {
    await page.getByLabel("Search users").fill(email);
    await page.getByRole("link", { name: /Bulk T/ }).first().click();
    page.once("dialog", (d) => d.accept());
    await page.getByRole("button", { name: "Delete user" }).click();
    await expect(page).toHaveURL(/\/admin\/users$/);
  }
  await page.getByLabel("Search users").fill(`T${tag}`);
  await expect(page.getByTestId("users-table")).not.toContainText(`T${tag}`);
});
