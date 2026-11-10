import { expect, test } from "@playwright/test";
import { loginAsAdmin } from "./helpers";

test.use({ viewport: { width: 1400, height: 1200 } });
const recipeName = `E2E scoped errors ${Date.now()}`;

test("wrap steps in a Handle errors block, give it error steps, and see the error datapills only there", async ({ page }) => {
  await loginAsAdmin(page);
  await page.goto("/admin/recipes");
  await page.getByRole("button", { name: "New recipe" }).click();
  await page.locator("#rc-name").fill(recipeName);
  await page.getByRole("button", { name: "Create and open builder" }).click();
  await page.getByTestId("studio-trigger").waitFor();
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(1500);   // the dev server remounts the page once; edits made before that are lost

  await page.getByTestId("studio-add").first().click();
  await page.getByRole("menuitem", { name: "Handle errors", exact: true }).click();
  await expect(page.getByTestId("handle-errors-help")).toBeVisible();

  const lane = () => page.getByRole("button", { name: "Add a step", exact: true });
  await lane().nth(0).click();   // the monitored steps (the block's first lane)
  await page.getByRole("menuitem", { name: "Write to the job log", exact: true }).click();

  await page.getByText("Write a log message").first().click();
  await page.getByLabel("Message", { exact: true }).fill("doing the work");

  await lane().nth(0).click();   // now the block's on-error lane is the first empty one
  await expect(page.getByRole("menuitem", { name: "Wait for approval", exact: true })).toHaveCount(0); // not allowed there
  await page.getByRole("menuitem", { name: "Write to the job log", exact: true }).click();
  await page.getByText("Write a log message").first().click();
  const msg = page.getByLabel("Message", { exact: true });
  await msg.fill("");
  await msg.pressSequentially("failed: {{error.me");
  await expect(page.getByTestId("pill-suggest")).toContainText("Error message");
  await page.keyboard.press("Enter");
  await expect(msg).toHaveValue("failed: {{error.message}}");

  await page.getByRole("button", { name: "Save draft" }).click();
  await expect(page.getByTestId("builder-msg")).toContainText("Draft saved");

  await page.goto("/admin/recipes");
  await page.getByTestId("recipes-table").locator("tr", { hasText: recipeName }).getByRole("button", { name: "Delete" }).click();
});
