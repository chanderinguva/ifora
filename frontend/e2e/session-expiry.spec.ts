import { expect, test } from "@playwright/test";
import { loginAsAdmin } from "./helpers";

test("an ended session sends the browser to the login page and back, never showing 'Not authenticated'", async ({ page, context }) => {
  await loginAsAdmin(page);

  // the session ends while the page is open; the next in-app data call redirects
  await context.clearCookies();
  await page.getByRole("link", { name: "Users", exact: true }).first().click();
  await expect(page).toHaveURL(/\/login\?next=%2Fadmin%2Fusers/);
  await expect(page.getByText("Not authenticated")).toHaveCount(0);

  // a refresh with no session lands on the same login URL
  await page.goto("/admin/groups");
  await expect(page).toHaveURL(/\/login\?next=%2Fadmin%2Fgroups/);
});
