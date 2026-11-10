import { expect, test } from "@playwright/test";
import { loginAsAdmin } from "./helpers";

test.use({ viewport: { width: 1400, height: 1000 } });
const recipeName = `E2E panel ${Date.now()}`;

test("the step panel can be resized by dragging or keyboard, and remembers its width", async ({ page }) => {
  await loginAsAdmin(page);
  await page.goto("/admin/recipes");
  await page.getByRole("button", { name: "New recipe" }).click();
  await page.locator("#rc-name").fill(recipeName);
  await page.getByRole("button", { name: "Create and open builder" }).click();
  await page.getByTestId("studio-trigger").waitFor();
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(1500);

  const panel = page.getByTestId("studio-panel");
  const handle = page.getByTestId("panel-resizer");
  const width = async () => Math.round((await panel.boundingBox())!.width);
  const start = await width();

  const hb = (await handle.boundingBox())!;
  await page.mouse.move(hb.x + hb.width / 2, hb.y + hb.height / 2);
  await page.mouse.down();
  await page.mouse.move(hb.x - 120, hb.y + hb.height / 2, { steps: 5 });
  await page.mouse.up();
  expect(await width()).toBeGreaterThan(start + 100);

  const wide = await width();
  await handle.focus();
  await page.keyboard.press("ArrowRight");
  expect(await width()).toBeLessThan(wide);

  const saved = await width();
  await page.reload();
  await page.getByTestId("studio-trigger").waitFor();
  expect(Math.abs((await width()) - saved)).toBeLessThanOrEqual(2);

  await handle.dblclick();
  expect(Math.abs((await width()) - 448)).toBeLessThanOrEqual(2);

  await page.goto("/admin/recipes");
  await page.getByTestId("recipes-table").locator("tr", { hasText: recipeName }).getByRole("button", { name: "Delete" }).click();
});
