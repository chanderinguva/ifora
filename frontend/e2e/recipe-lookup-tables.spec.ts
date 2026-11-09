import { expect, test } from "@playwright/test";
import { ADMIN_EMAIL, loginAsAdmin } from "./helpers";

test.use({ viewport: { width: 1280, height: 1100 } });
const stamp = Date.now();
const tableName = `e2e_lt_${stamp}`;
const recipeName = `E2E lookup ${stamp}`;

test("create a lookup table, edit rows, import CSV, and read a row from a recipe test run", async ({ page }) => {
  await loginAsAdmin(page);
  page.on("dialog", (d) => d.accept());

  // the table
  await page.goto("/admin/recipes/lookup-tables");
  await page.getByTestId("new-table").click();
  await page.locator("#lt-name").fill(tableName);
  await page.getByRole("button", { name: "Create table" }).click();
  await expect(page.getByTestId("table-view")).toContainText(tableName);

  await page.getByTestId("add-row").click();
  await page.getByTestId("row-editor").getByLabel("code").fill("ENG");
  await page.getByTestId("row-editor").getByLabel("value").fill("eng-value");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByTestId("rows-table")).toContainText("eng-value");

  // a duplicate key is refused with a clear message
  await page.getByTestId("add-row").click();
  await page.getByTestId("row-editor").getByLabel("code").fill("ENG");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByRole("status").filter({ hasText: "already exists" })).toBeVisible();
  await page.getByRole("button", { name: "Cancel" }).click();

  // CSV import is all or nothing
  await page.getByRole("button", { name: "Import CSV" }).click();
  await page.getByLabel("CSV text").fill("code,value\nOPS,ops-value\nENG,again\n");
  await page.getByTestId("csv-import").getByRole("button", { name: "Import", exact: true }).click();
  await expect(page.getByRole("status").filter({ hasText: "Nothing was imported" })).toBeVisible();
  await page.getByLabel("CSV text").fill("code,value\nOPS,ops-value\n");
  await page.getByTestId("csv-import").getByRole("button", { name: "Import", exact: true }).click();
  await expect(page.getByTestId("rows-table")).toContainText("ops-value");
  await expect(page.getByTestId("row")).toHaveCount(2);

  // a recipe reads a row
  await page.goto("/admin/recipes");
  await page.getByRole("button", { name: "New recipe" }).click();
  await page.locator("#rc-name").fill(recipeName);
  await page.getByRole("button", { name: "Create and open builder" }).click();
  await page.getByTestId("try-studio").click();
  const add = async (label: string) => {
    await page.getByTestId("studio-add").first().click();
    await page.getByRole("menuitem", { name: label, exact: true }).click();
  };
  await add("Write to the job log");
  await add("Look up a row");
  await page.getByLabel("Lookup table", { exact: true }).selectOption(tableName);
  await page.getByLabel("Lookup value", { exact: true }).fill("ENG");
  await page.getByText("Write a log message").click();
  const msg = page.getByLabel("Message", { exact: true });
  await msg.fill("");
  await msg.pressSequentially("found={{steps.s2.output.found}} value={{steps.s2.output.row.va");
  await expect(page.getByTestId("pill-suggest")).toContainText("row value");
  await page.keyboard.press("Enter");
  await page.getByRole("button", { name: "Save draft" }).click();
  await expect(page.getByTestId("builder-msg")).toContainText("Draft saved");
  await page.getByLabel("Sample user").selectOption({ label: ADMIN_EMAIL });
  await page.getByRole("button", { name: "Run test" }).click();
  await expect(page.getByTestId("job-view")).toContainText("found=true value=eng-value");

  // a table that a recipe uses cannot be deleted; clean up in order
  await page.goto("/admin/recipes/lookup-tables");
  await page.getByTestId("table-list").getByText(tableName).click();
  await page.getByRole("button", { name: "Delete", exact: true }).click();
  await expect(page.getByRole("status").filter({ hasText: "Used by recipes" })).toBeVisible();
  await page.goto("/admin/recipes");
  const row = page.getByTestId("recipes-table").locator("tr", { hasText: recipeName });
  await row.getByRole("button", { name: "Delete" }).click();
  await expect(page.getByTestId("recipes-table")).not.toContainText(recipeName);
  await page.goto("/admin/recipes/lookup-tables");
  await page.getByTestId("table-list").getByText(tableName).click();
  await page.getByRole("button", { name: "Delete", exact: true }).click();
  await expect(page.getByTestId("table-list")).not.toContainText(tableName);
});
