import { expect, test } from "@playwright/test";
import { loginAsAdmin } from "./helpers";

const run = Date.now();
const email = `e2e.rules.${run}@example.com`;
const groupName = `E2E Sales ${run}`;
const ruleName = `E2E rule ${run}`;

test("a group rule adds matching users automatically and keeps them in step", async ({ page }) => {
  await loginAsAdmin(page);

  // group
  await page.goto("/admin/groups");
  await page.getByRole("button", { name: "New group" }).click();
  await page.locator("#g-name").fill(groupName);
  await page.getByRole("button", { name: "Create group" }).click();
  await expect(page.getByRole("link", { name: groupName })).toBeVisible();

  // user created with a generated password and a department
  await page.goto("/admin/users");
  await page.getByRole("button", { name: "New user" }).click();
  await page.locator("#nu-first").fill("Rule");
  await page.locator("#nu-last").fill("Target");
  await page.locator("#nu-email").fill(email);
  await page.locator("#nu-department").fill("Sales");
  await page.getByRole("button", { name: "Create user" }).click();
  await expect(page.getByTestId("temp-password")).toHaveText(/^[A-Za-z0-9]{20}$/);
  await page.getByRole("button", { name: "Done" }).click();

  // rule: department equals Sales -> group; preview, save, activate
  await page.goto("/admin/group-rules");
  await page.getByRole("button", { name: "Add rule" }).click();
  await page.locator("#r-name").fill(ruleName);
  await page.getByLabel("Value").fill("Sales");
  await page.getByLabel(groupName).check();
  await page.getByRole("button", { name: "Preview matches" }).click();
  await expect(page.getByTestId("rule-preview")).toContainText(email);
  await page.getByRole("button", { name: "Save rule" }).click();
  const row = page.getByTestId("rules-table").locator("tr", { hasText: ruleName });
  await expect(row).toContainText("inactive");
  await row.getByRole("button", { name: "Activate" }).click();
  await expect(row).toContainText("active");
  await expect(row).toContainText('user.department equals "Sales"');

  // membership shows up, marked as rule-managed, and cannot be removed by hand
  await page.goto("/admin/groups");
  await page.getByRole("link", { name: groupName }).click();
  const member = page.getByTestId("members-table").locator("tr", { hasText: email });
  await expect(member).toContainText("via rule");
  await expect(member.getByRole("button", { name: "Remove" })).toBeDisabled();

  // clean up: delete rule (removes its memberships), group, user
  page.on("dialog", (d) => d.accept());
  await page.goto("/admin/group-rules");
  await page.getByTestId("rules-table").locator("tr", { hasText: ruleName }).getByRole("button", { name: "Delete" }).click();
  await expect(page.getByTestId("rules-table")).not.toContainText(ruleName);
  await page.goto("/admin/groups");
  await page.getByRole("link", { name: groupName }).click();
  await page.getByRole("button", { name: "Delete group" }).click();
  await page.goto("/admin/users");
  await page.getByLabel("Search users").fill(email);
  await page.getByRole("link", { name: "Rule Target" }).click();
  await page.getByRole("button", { name: "Delete user" }).click();
  await expect(page).toHaveURL(/\/admin\/users$/);
});
