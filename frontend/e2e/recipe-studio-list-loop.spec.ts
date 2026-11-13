import { expect, test } from "@playwright/test";
import { ADMIN_EMAIL, loginAsAdmin } from "./helpers";

test.use({ viewport: { width: 1280, height: 1100 } });
const recipeName = `E2E list loop ${Date.now()}`;

test("repeat a step for each item of a list and see every item in the test run", async ({ page }) => {
  await loginAsAdmin(page);
  page.on("dialog", (d) => d.accept());
  await page.goto("/admin/recipes");
  await page.getByRole("button", { name: "New recipe" }).click();
  await page.locator("#rc-name").fill(recipeName);
  await page.getByRole("button", { name: "Create and open builder" }).click();

  await page.getByTestId("studio-add").first().click();
  await page.getByRole("menuitem", { name: "For each item in a list", exact: true }).click();
  await page.getByLabel("Loop list", { exact: true }).fill('{{= split("red,green,blue", ",") }}');

  // the loop's own lane is empty, so its button is the only "Add a step"
  await page.getByRole("button", { name: "Add a step", exact: true }).first().click();
  await page.getByRole("menuitem", { name: "Write to the job log", exact: true }).click();
  await page.getByText("Write a log message").click();
  const msg = page.getByLabel("Message", { exact: true });
  await msg.fill("");
  await msg.pressSequentially("item {{loop.it");
  await expect(page.getByTestId("pill-suggest")).toContainText("Current item");
  await page.keyboard.press("Enter");
  await expect(msg).toHaveValue("item {{loop.item}}");

  await page.getByRole("button", { name: "Save draft" }).click();
  await expect(page.getByTestId("builder-msg")).toContainText("Draft saved");
  await page.getByLabel("Sample user").selectOption({ label: ADMIN_EMAIL });
  await page.getByRole("button", { name: "Validate draft" }).click();
  await expect(page.getByTestId("job-view")).toContainText("succeeded");
  for (const c of ["item red", "item green", "item blue"]) await expect(page.getByTestId("job-view")).toContainText(c);

  await page.goto("/admin/recipes");
  const row = page.getByTestId("recipes-table").locator("tr", { hasText: recipeName });
  await row.getByRole("button", { name: "Delete" }).click();
  await expect(page.getByTestId("recipes-table")).not.toContainText(recipeName);
});
