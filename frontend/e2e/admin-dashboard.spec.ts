import { expect, test } from "@playwright/test";
import { loginAsAdmin } from "./helpers";

test("admin dashboard: tasks link to the thing to fix, widgets render, status deep-link filters users", async ({ page }) => {
  await loginAsAdmin(page);
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();

  // the throwaway admin has no second factor, so that task must be listed and must link to Users
  await expect(page.getByTestId("tasks")).toBeVisible();
  const task = page.getByTestId("task-admins_no_mfa");
  await expect(task).toContainText("without a second factor");
  await expect(page.getByTestId("widgets")).toContainText("Sign-ins, last 7 days");
  await expect(page.getByTestId("widgets")).toContainText("Users by status");
  await expect(page.getByTestId("widgets")).toContainText("Applications");
  await expect(page.getByRole("img", { name: /Sign-ins per day/ })).toBeVisible();

  await task.click();
  await expect(page).toHaveURL(/\/admin\/users$/);

  // deep link from a task pre-selects the status filter
  await page.goto("/admin/users?status=locked_out");
  await expect(page.getByLabel("Filter by status")).toHaveValue("locked_out");
});
