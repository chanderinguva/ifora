import { expect, test } from "@playwright/test";
import { loginAsAdmin } from "./helpers";

test.use({ viewport: { width: 1400, height: 1400 } });
const recipeName = `E2E else-if ${Date.now()}`;

test("build an if / else-if / else chain, edit a link, and save it", async ({ page }) => {
  await loginAsAdmin(page);
  await page.goto("/admin/recipes");
  await page.getByRole("button", { name: "New recipe" }).click();
  await page.locator("#rc-name").fill(recipeName);
  await page.getByRole("button", { name: "Create and open builder" }).click();
  await page.getByTestId("try-studio").click();
  await page.getByTestId("studio-trigger").waitFor();
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(1500);   // the dev server remounts the page once; edits made before that are lost

  await page.getByTestId("studio-add").first().click();
  await page.getByRole("menuitem", { name: "If / else", exact: true }).click();

  // no "else if" yet; add two links, one under the other, then a step in the final otherwise
  await expect(page.getByTestId("else-if")).toHaveCount(0);
  await page.getByTestId("add-else-if").click();
  await expect(page.getByTestId("else-if")).toHaveCount(1);
  await page.getByTestId("add-else-if").click();   // the button now sits under the last link
  await expect(page.getByTestId("else-if")).toHaveCount(2);
  await expect(page.getByTestId("add-else-if")).toHaveCount(1);

  // a link is selectable and has the condition form
  await page.getByRole("button", { name: "Open else-if condition" }).first().click();
  await expect(page.getByRole("button", { name: "Open else-if condition" }).first()).toHaveAttribute("aria-pressed", "true");

  // a step can go in the last link's otherwise lane
  await page.getByRole("button", { name: "Add a step", exact: true }).last().click();
  await page.getByRole("menuitem", { name: "Write to the job log", exact: true }).click();
  await page.getByText("Write a log message").first().click();
  await page.getByLabel("Message", { exact: true }).fill("fallback");

  await page.getByRole("button", { name: "Save draft" }).click();
  await expect(page.getByTestId("builder-msg")).toContainText("Draft saved");

  // deleting the first link takes the rest of the chain with it
  await page.getByRole("button", { name: "Delete else-if" }).first().click();
  await expect(page.getByTestId("else-if")).toHaveCount(0);
  await expect(page.getByTestId("add-else-if")).toHaveCount(1);

  await page.goto("/admin/recipes");
  await page.getByTestId("recipes-table").locator("tr", { hasText: recipeName }).getByRole("button", { name: "Delete" }).click();
});
