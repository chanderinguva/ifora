import { expect, test } from "@playwright/test";
import { ADMIN_EMAIL, loginAsAdmin } from "./helpers";

test.use({ viewport: { width: 1280, height: 1100 } });
const recipeName = `E2E flow steps ${Date.now()}`;

test("set a variable, use it later, add a wait and a throttle, and run a test without pausing", async ({ page }) => {
  await loginAsAdmin(page);
  page.on("dialog", (d) => d.accept());
  await page.goto("/admin/recipes");
  await page.getByRole("button", { name: "New recipe" }).click();
  await page.locator("#rc-name").fill(recipeName);
  await page.getByRole("button", { name: "Create and open builder" }).click();

  // each new step goes into the first slot of the main flow, so add them last-to-first
  const add = async (label: string) => {
    await page.getByTestId("studio-add").first().click();
    await page.getByRole("menuitem", { name: label, exact: true }).click();
  };

  await add("Write to the job log");
  await add("Wait (delay)");
  await page.getByLabel("Wait amount").fill("2");
  await page.getByLabel("Wait unit").selectOption("days");
  await add("Throttle");
  await page.getByLabel("Throttle max runs").fill("5");
  await page.getByLabel("Throttle window minutes").fill("10");
  await page.getByLabel("Throttle when full").selectOption("stop");
  await add("Set a variable");
  await page.getByLabel("Variable name", { exact: true }).fill("total");
  await page.getByLabel("Variable value", { exact: true }).fill("{{= 2 + 3 }}");

  await page.getByText("Write a log message").click();
  const msg = page.getByLabel("Message", { exact: true });
  await msg.fill("");
  await msg.pressSequentially("total is {{vars.to");
  await expect(page.getByTestId("pill-suggest")).toContainText("Variable: total");
  await page.keyboard.press("Enter");
  await expect(msg).toHaveValue("total is {{vars.total}}");

  await page.getByRole("button", { name: "Save draft" }).click();
  await expect(page.getByTestId("builder-msg")).toContainText("Draft saved");
  await page.getByLabel("Sample user").selectOption({ label: ADMIN_EMAIL });
  await page.getByRole("button", { name: "Validate draft" }).click();
  await expect(page.getByTestId("job-view")).toContainText("total is 5");
  await expect(page.getByTestId("job-view")).toContainText("succeeded");

  await page.goto("/admin/recipes");
  const row = page.getByTestId("recipes-table").locator("tr", { hasText: recipeName });
  await row.getByRole("button", { name: "Delete" }).click();
  await expect(page.getByTestId("recipes-table")).not.toContainText(recipeName);
});
