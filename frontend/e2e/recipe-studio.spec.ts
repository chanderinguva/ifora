import { expect, test } from "@playwright/test";
import { ADMIN_EMAIL, loginAsAdmin } from "./helpers";

const recipeName = `E2E studio ${Date.now()}`;

test("build a recipe in the studio editor: add, nest, duplicate, undo, delete, test, save", async ({ page }) => {
  await loginAsAdmin(page);
  page.on("dialog", (d) => d.accept());

  await page.goto("/admin/recipes");
  await page.getByRole("button", { name: "New recipe" }).click();
  await page.locator("#rc-name").fill(recipeName);
  await page.getByRole("button", { name: "Create and open builder" }).click();
  await expect(page.getByRole("heading", { name: recipeName })).toBeVisible();
  await expect(page.getByTestId("studio")).toBeVisible();

  const cards = page.getByTestId("studio-card");
  const addStep = async (nth: number, name: string) => {
    await page.getByTestId("studio-add").nth(nth).click();
    await page.getByRole("menuitem", { name, exact: true }).click();
  };

  // first step from the empty state; its form opens in the side panel
  await page.getByRole("button", { name: "Add a step", exact: true }).first().click();
  await page.getByRole("menuitem", { name: "Write to the job log", exact: true }).click();
  await expect(cards).toHaveCount(1);
  await page.getByLabel("Message", { exact: true }).fill("hello {{trigger.user.email}}");
  await expect(cards.first()).toContainText("hello");

  // a condition after it, and a step nested in its "yes" branch
  await addStep(1, "If / else");
  await expect(cards).toHaveCount(2);
  await page.getByTestId("studio-card").nth(1).getByTestId("studio-add").first().click();
  await page.getByRole("menuitem", { name: "Write to the job log", exact: true }).click();
  await expect(cards).toHaveCount(3);
  await page.getByLabel("Message", { exact: true }).fill("nested");   // the new step is selected; the server rejects an empty message

  // duplicate the first step, then undo it
  await cards.first().getByRole("button", { name: "Duplicate step" }).click();
  await expect(cards).toHaveCount(4);
  await page.getByRole("button", { name: "Undo" }).click();
  await expect(cards).toHaveCount(3);
  await page.getByRole("button", { name: "Redo" }).click();
  await expect(cards).toHaveCount(4);

  // delete the duplicate with the button
  await cards.nth(1).getByRole("button", { name: "Delete step" }).click();
  await expect(cards).toHaveCount(3);

  // save and dry-run
  await page.getByRole("button", { name: "Save draft" }).click();
  await expect(page.getByTestId("builder-msg")).toContainText("Draft saved");
  await page.getByLabel("Sample user").selectOption({ label: ADMIN_EMAIL });
  await page.getByRole("button", { name: "Run test" }).click();
  await expect(page.getByTestId("job-view")).toContainText("Test run (nothing was changed)");

  // clean up
  await page.goto("/admin/recipes");
  const row = page.getByTestId("recipes-table").locator("tr", { hasText: recipeName });
  await row.getByRole("button", { name: "Delete" }).click();
  await expect(page.getByTestId("recipes-table")).not.toContainText(recipeName);
});
