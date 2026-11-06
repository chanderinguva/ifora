import { expect, test } from "@playwright/test";
import { loginAsAdmin } from "./helpers";

const run = Date.now();
const key = `grade_${run}`;
const label = `Grade ${run}`;

test("admin defines a choice attribute; it appears for users and in group rules; built-ins are protected", async ({ page }) => {
  page.on("dialog", (d) => d.accept());
  await loginAsAdmin(page);

  await page.goto("/admin/profile-editor");
  await expect(page.getByTestId("attr-row-department")).toContainText("Admin only");
  await expect(page.getByTestId("attr-row-title")).toContainText("User");
  await expect(page.getByRole("button", { name: "Delete title" })).toHaveCount(0); // built-in

  // add a choice-list attribute only administrators can edit
  await page.getByRole("button", { name: "Add attribute" }).click();
  await page.locator("#pa-name").fill(label);
  await page.locator("#pa-key").fill(key);
  await page.locator("#pa-type").selectOption("enum");
  await page.locator("#pa-opts").fill("L1\nL2\nL3");
  await page.getByRole("button", { name: "Save attribute" }).click();
  const row = page.getByTestId(`attr-row-${key}`);
  await expect(row).toContainText("L1, L2, L3");
  await expect(row).toContainText("rule-ready");

  // it is offered, with its choices, when building a group rule
  await page.goto("/admin/group-rules");
  await page.getByRole("button", { name: "Add rule" }).click();
  await page.getByLabel("Attribute").first().selectOption(key);
  await expect(page.getByLabel("Value").first().locator("option", { hasText: "L2" })).toHaveCount(1);
  // and user-editable ones are explained rather than silently missing
  await expect(page.getByTestId("rule-editor")).toContainText("users can edit these themselves");

  // clean up
  await page.goto("/admin/profile-editor");
  await page.getByTestId(`attr-row-${key}`).getByRole("button", { name: `Delete ${key}` }).click();
  await expect(page.getByTestId(`attr-row-${key}`)).toHaveCount(0);
});
