import { expect, test } from "@playwright/test";
import { ADMIN_EMAIL, loginAsAdmin } from "./helpers";

// NOTE: written for the recipe builder (ADR 008) but not executed by its author; run it against a stack that has
// this branch built. The worker is not needed: the test only exercises the builder, dry run, publish and enable.
const run = Date.now();
const groupName = `E2E Recipe Group ${run}`;
const recipeName = `E2E recipe ${run}`;

test("build, dry-run, publish and enable a recipe with typed selects and datapills", async ({ page }) => {
  await loginAsAdmin(page);
  page.on("dialog", (d) => d.accept());

  // a real group for the group select
  await page.goto("/admin/groups");
  await page.getByRole("button", { name: "New group" }).click();
  await page.locator("#g-name").fill(groupName);
  await page.getByRole("button", { name: "Create group" }).click();
  await expect(page.getByRole("link", { name: groupName })).toBeVisible();

  // new recipe
  await page.goto("/admin/recipes");
  await page.getByRole("button", { name: "New recipe" }).click();
  await page.locator("#rc-name").fill(recipeName);
  await page.getByRole("button", { name: "Create and open builder" }).click();
  await expect(page.getByRole("heading", { name: recipeName })).toBeVisible();

  // trigger: a user is created (default). Step 1: add the user to the group (typed select, not free text)
  await page.getByLabel("New step type").first().selectOption("add_to_group");
  await page.getByRole("button", { name: "Add step" }).first().click();
  await page.getByLabel("Group", { exact: true }).selectOption({ label: groupName });

  // step 2: log a message built with the datapill picker
  await page.getByLabel("New step type").first().selectOption("log");
  await page.getByRole("button", { name: "Add step" }).first().click();
  await page.getByLabel("Insert datapill into Message").selectOption("trigger.user.email");
  await expect(page.getByLabel("Message", { exact: true })).toHaveValue("{{trigger.user.email}}");

  // the condition editor offers no self-editable fields
  await page.getByLabel("New step type").first().selectOption("condition");
  await page.getByRole("button", { name: "Add step" }).first().click();
  const fieldOptions = await page.getByLabel("Field").first().locator("option").allTextContents();
  expect(fieldOptions.join("|")).not.toContain("First name");

  await page.getByRole("button", { name: "Delete step" }).last().click();
  await page.getByRole("button", { name: "Save draft" }).click();
  await expect(page.getByRole("status")).toContainText("Draft saved");

  // dry run against a real user
  await page.getByLabel("Sample user").selectOption({ label: ADMIN_EMAIL });
  await page.getByRole("button", { name: "Run test" }).click();
  const job = page.getByTestId("job-view");
  await expect(job).toContainText("Test run (nothing was changed)");
  await expect(job.getByTestId("job-step")).toHaveCount(2);

  // publish and enable
  await page.getByRole("button", { name: "Publish" }).click();
  await expect(page.getByRole("status")).toContainText("Published");
  await page.getByRole("button", { name: "Enable", exact: true }).click();
  await page.goto("/admin/recipes");
  const row = page.getByTestId("recipes-table").locator("tr", { hasText: recipeName });
  await expect(row).toContainText("enabled");
  await expect(row).toContainText("v1");

  // clean up
  await row.getByRole("button", { name: "Delete" }).click();
  await expect(page.getByTestId("recipes-table")).not.toContainText(recipeName);
  await page.goto("/admin/groups");
  await page.getByRole("link", { name: groupName }).click();
  await page.getByRole("button", { name: "Delete group" }).click();
});
