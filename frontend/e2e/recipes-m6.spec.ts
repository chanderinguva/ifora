import { readFileSync } from "fs";
import { expect, test } from "@playwright/test";
import { loginAsAdmin } from "./helpers";

// R-M6: start from a template, look at it in the studio, export the recipe and import it again.
const run = Date.now();
const groupName = `E2E Tpl Group ${run}`;
const recipeName = `E2E template recipe ${run}`;

test("template -> studio -> export -> import", async ({ page }) => {
  test.setTimeout(120_000);
  page.on("dialog", (d) => d.accept());
  await loginAsAdmin(page);

  await page.goto("/admin/groups");
  await page.getByRole("button", { name: "New group" }).click();
  await page.locator("#g-name").fill(groupName);
  await page.getByRole("button", { name: "Create group" }).click();
  await expect(page.getByRole("link", { name: groupName })).toBeVisible();

  // from a template
  await page.goto("/admin/recipes");
  await page.getByRole("button", { name: "From template" }).click();
  await page.getByRole("button", { name: /Group access that needs an approval/ }).click();
  await page.locator("#tp-name").fill(recipeName);
  await page.locator("#tp-group").selectOption({ label: groupName });
  await page.getByRole("button", { name: "Create draft from template" }).click();
  await expect(page.getByRole("heading", { name: recipeName })).toBeVisible();

  // the template opens straight in the studio editor, with its approval step on the canvas
  await expect(page.getByTestId("studio")).toContainText("Wait for approval");

  // export downloads a secret-free file
  const [download] = await Promise.all([page.waitForEvent("download"), page.getByRole("button", { name: "Export" }).click()]);
  const path = await download.path();
  const doc = JSON.parse(readFileSync(path!, "utf8"));
  expect(doc.format).toBe("identityforge.recipe");
  expect(doc.references.groups).toMatchObject({ [Object.keys(doc.references.groups)[0]]: groupName });

  // import it again under another name
  await page.goto("/admin/recipes");
  await page.getByRole("button", { name: "Import", exact: true }).click();
  await page.locator("#imp-file").setInputFiles(path!);
  await page.locator("#imp-name").fill(`${recipeName} copy`);
  await page.getByRole("button", { name: "Import as draft" }).click();
  await expect(page.getByRole("heading", { name: `${recipeName} copy` })).toBeVisible();

  // clean up both recipes and the group
  for (const n of [`${recipeName} copy`, recipeName]) {
    await page.goto("/admin/recipes");
    await page.getByTestId("recipes-table").locator("tr", { hasText: n }).getByRole("button", { name: "Delete" }).click();
    await expect(page.getByTestId("recipes-table")).not.toContainText(n);
  }
  await page.goto("/admin/groups");
  await page.getByRole("link", { name: groupName }).click();
  await page.getByRole("button", { name: /Delete group/ }).click();
});
