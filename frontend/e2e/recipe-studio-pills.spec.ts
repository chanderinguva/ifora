import { expect, test } from "@playwright/test";
import { loginAsAdmin } from "./helpers";

test.use({ viewport: { width: 1280, height: 1100 } });
const recipeName = `E2E studio pills ${Date.now()}`;

test("datapills: type {{ to search, click a tray chip, drag a chip onto a field, and see chips for the stored text", async ({ page }) => {
  await loginAsAdmin(page);
  page.on("dialog", (d) => d.accept());
  await page.goto("/admin/recipes");
  await page.getByRole("button", { name: "New recipe" }).click();
  await page.locator("#rc-name").fill(recipeName);
  await page.getByRole("button", { name: "Create and open builder" }).click();
  await page.getByRole("button", { name: "Add a step", exact: true }).first().click();
  await page.getByRole("menuitem", { name: "Write to the job log", exact: true }).click();

  const msg = page.getByLabel("Message", { exact: true });
  const preview = page.getByTestId("pill-preview");

  // typing {{ opens a searchable list; Enter picks the highlighted entry
  await msg.fill("");
  await msg.pressSequentially("Hi {{email");
  await expect(page.getByTestId("pill-suggest")).toBeVisible();
  await page.keyboard.press("Enter");
  await expect(msg).toHaveValue("Hi {{trigger.user.email}}");
  await expect(preview).toContainText("Hi");
  await expect(preview.locator("span[title='trigger.user.email']")).toBeVisible();

  // clicking a tray chip inserts at the field used last
  await page.getByTestId("pill-tray").getByLabel("Search data").fill("username");
  await page.getByTestId("pill-chip").first().click();
  await expect(msg).toHaveValue(/\{\{trigger\.user\.email\}\}.*\{\{trigger\.user\.username\}\}/);

  // dragging a chip onto the field inserts it too
  await page.getByTestId("pill-tray").getByLabel("Search data").fill("");
  await msg.fill("Drop: ");
  const chip = page.locator('[data-testid="pill-chip"][data-path="trigger.user.id"]');
  const c = (await chip.boundingBox())!;
  const f = (await msg.boundingBox())!;
  await page.mouse.move(c.x + c.width / 2, c.y + c.height / 2);
  await page.mouse.down();
  await page.mouse.move(c.x + c.width / 2 + 10, c.y + c.height / 2 + 10, { steps: 4 });
  await page.mouse.move(f.x + f.width / 2, f.y + f.height / 2, { steps: 8 });
  await page.mouse.up();
  await expect(msg).toHaveValue("Drop: {{trigger.user.id}}");

  // a pill that is not available at this step is flagged
  await msg.fill("{{steps.s9.output.x}}");
  await expect(preview.locator("span[title='Not available at this step']")).toBeVisible();

  await page.goto("/admin/recipes");
  const row = page.getByTestId("recipes-table").locator("tr", { hasText: recipeName });
  await row.getByRole("button", { name: "Delete" }).click();
  await expect(page.getByTestId("recipes-table")).not.toContainText(recipeName);
});
