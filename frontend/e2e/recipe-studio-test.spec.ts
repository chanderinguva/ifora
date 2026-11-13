import { expect, test } from "@playwright/test";
import { ADMIN_EMAIL, loginAsAdmin } from "./helpers";

test.use({ viewport: { width: 1280, height: 1300 } });
const recipeName = `E2E studio test ${Date.now()}`;

test("test results on the cards, step notes, handle-errors section and restoring a version", async ({ page }) => {
  await loginAsAdmin(page);
  page.on("dialog", (d) => d.accept());
  await page.goto("/admin/recipes");
  await page.getByRole("button", { name: "New recipe" }).click();
  await page.locator("#rc-name").fill(recipeName);
  await page.getByRole("button", { name: "Create and open builder" }).click();

  const cards = page.getByTestId("studio-card");
  const msg = page.getByLabel("Message", { exact: true });

  // log "first", then an if/else with a log in each branch
  await page.getByRole("button", { name: "Add a step", exact: true }).first().click();
  await page.getByRole("menuitem", { name: "Write to the job log", exact: true }).click();
  await msg.fill("first");
  await page.getByTestId("studio-add").nth(1).click();
  await page.getByRole("menuitem", { name: "If / else", exact: true }).click();
  const cond = cards.filter({ hasText: "If / else" });
  await cond.getByTestId("studio-add").nth(0).click();
  await page.getByRole("menuitem", { name: "Write to the job log", exact: true }).click();
  await msg.fill("yes branch");
  await cond.getByTestId("studio-add").nth(2).click();   // 0, 1 are the "yes" lane (before and after its step); 2 is the empty "otherwise" lane
  await page.getByRole("menuitem", { name: "Write to the job log", exact: true }).click();
  await msg.fill("no branch");
  await expect(cards).toHaveCount(4);

  // a note shows on the card
  await cards.first().getByRole("button", { name: /Open step 1/ }).click();
  await page.getByLabel("Note (optional)").fill("Shows the flow works");
  await expect(cards.first().getByTestId("step-note")).toHaveText("Shows the flow works");

  // the handle-errors section is there
  await expect(page.getByTestId("handle-errors")).toContainText("Handle errors");

  // test run: the taken branch is green, the other is grey
  await page.getByRole("button", { name: "Save draft" }).click();
  await expect(page.getByTestId("builder-msg")).toContainText("Draft saved");
  await page.getByLabel("Sample user").selectOption({ label: ADMIN_EMAIL });
  await page.getByRole("button", { name: "Validate draft" }).click();
  const dots = cards.locator('[data-testid="step-result"]');   // on the cards, not the side panel
  await expect(dots).toHaveCount(4);
  await expect(cards.locator('[data-testid="step-result"][data-outcome="ok"]')).toHaveCount(3);
  await expect(cards.locator('[data-testid="step-result"][data-outcome="skipped"]')).toHaveCount(1);
  await cards.first().getByRole("button", { name: /Open step 1/ }).click();
  await expect(page.getByTestId("step-result-panel")).toContainText("Input (redacted)");
  await page.getByRole("button", { name: /Open step/ }).filter({ hasText: "no branch" }).click();
  await expect(page.getByTestId("step-result-panel")).toContainText("did not run");

  // changing the draft marks the results as old
  await cards.first().getByRole("button", { name: /Open step 1/ }).click();
  await msg.fill("first, edited");
  await expect(page.getByTestId("result-note")).toContainText("earlier draft");

  // publish v1 with "first, edited", change it again, then restore v1 into the draft
  await page.getByRole("button", { name: "Save draft" }).click();
  await page.getByRole("button", { name: "Publish" }).click();
  await expect(page.getByTestId("builder-msg")).toContainText("Published");
  await msg.fill("third");
  await page.getByRole("button", { name: "Save draft" }).click();
  await expect(page.getByTestId("builder-msg")).toContainText("Draft saved");
  await page.getByRole("button", { name: "Restore version 1 to the draft" }).click();
  await expect(page.getByTestId("builder-msg")).toContainText("Version 1 copied into the draft");
  await expect(cards.first()).toContainText("first, edited");

  await page.goto("/admin/recipes");
  const row = page.getByTestId("recipes-table").locator("tr", { hasText: recipeName });
  await row.getByRole("button", { name: "Delete" }).click();
  await expect(page.getByTestId("recipes-table")).not.toContainText(recipeName);
});
