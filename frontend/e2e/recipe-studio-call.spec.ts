import { expect, test } from "@playwright/test";
import { ADMIN_EMAIL, loginAsAdmin } from "./helpers";

test.use({ viewport: { width: 1280, height: 1100 } });
const stamp = Date.now();
const calleeName = `E2E callee ${stamp}`;
const callerName = `E2E caller ${stamp}`;

async function createRecipe(page: import("@playwright/test").Page, name: string) {
  await page.goto("/admin/recipes");
  await page.getByRole("button", { name: "New recipe" }).click();
  await page.locator("#rc-name").fill(name);
  await page.getByRole("button", { name: "Create and open builder" }).click();
  // next dev compiles the studio page on first use and then reloads it, which drops edits made meanwhile: reload once so it is warm
  await expect(page.getByTestId("studio-trigger")).toBeVisible();
  await page.reload();
  await expect(page.getByTestId("studio-trigger")).toBeVisible();
  await page.waitForLoadState("networkidle");
}

test("call another recipe, pass an input and use the data it returns", async ({ page }) => {
  await loginAsAdmin(page);
  page.on("dialog", (d) => d.accept());

  // 1. a callable recipe: one number input, one output
  await createRecipe(page, calleeName);
  await page.getByLabel("Trigger", { exact: true }).selectOption("call");
  await page.getByRole("button", { name: "Add input" }).click();
  await page.getByLabel("Input name 1").fill("n");
  await page.getByLabel("Input type 1").selectOption("number");
  await page.locator("#call-outputs").fill("double");
  await page.getByTestId("studio-add").first().click();
  await page.getByRole("menuitem", { name: "Return data to the caller", exact: true }).click();
  await page.getByLabel("Return double", { exact: true }).fill("{{= number(trigger.payload.n) * 2 }}");
  await page.getByRole("button", { name: "Save draft" }).click();
  await expect(page.getByTestId("builder-msg")).toContainText("Draft saved");
  await page.getByRole("button", { name: "Publish" }).click();
  await expect(page.getByTestId("builder-msg")).toContainText("Published");
  await page.getByRole("button", { name: "Enable", exact: true }).click();

  // 2. a caller
  await createRecipe(page, callerName);
  await page.getByTestId("studio-add").first().click();
  await page.getByRole("menuitem", { name: "Write to the job log", exact: true }).click();
  await page.getByText("Write a log message").click();
  await page.getByLabel("Message", { exact: true }).fill("doubled: {{steps.s2.output.result.double}}");
  await page.getByTestId("studio-add").first().click();
  await page.getByRole("menuitem", { name: "Call a recipe", exact: true }).click();
  await page.getByLabel("Recipe to call", { exact: true }).selectOption({ label: calleeName });
  await page.getByLabel("Call input n", { exact: true }).fill("21");
  await page.getByRole("button", { name: "Save draft" }).click();
  await expect(page.getByTestId("builder-msg")).toContainText("Draft saved");
  await page.getByLabel("Sample user").selectOption({ label: ADMIN_EMAIL });
  await page.getByRole("button", { name: "Run test" }).click();
  await expect(page.getByTestId("job-view")).toContainText("succeeded");
  await expect(page.getByTestId("job-view")).toContainText("doubled: 42");

  for (const n of [callerName, calleeName]) {
    await page.goto("/admin/recipes");
    await page.getByTestId("recipes-table").locator("tr", { hasText: n }).getByRole("button", { name: "Delete" }).click();
    await expect(page.getByTestId("recipes-table")).not.toContainText(n);
  }
});
