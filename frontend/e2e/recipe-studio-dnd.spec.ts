import { expect, test, type Locator, type Page } from "@playwright/test";
import { loginAsAdmin } from "./helpers";

test.use({ viewport: { width: 1280, height: 800 } });   // a normal window: cards below the fold are reached by scrolling

const recipeName = `E2E studio dnd ${Date.now()}`;

async function dragTo(page: Page, handle: Locator, gap: string) {
  await handle.scrollIntoViewIfNeeded();
  const box = (await handle.boundingBox())!;
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width / 2 + 12, box.y + box.height / 2 + 12, { steps: 4 });
  const slot = page.locator(`[data-gap="${gap}"]`);
  await expect(slot).toBeVisible();
  const s = (await slot.boundingBox())!;
  await page.mouse.move(s.x + s.width / 2, s.y + s.height / 2, { steps: 8 });
  await page.mouse.up();
  await page.waitForTimeout(350);
}

test("reorder and nest steps by dragging, move with the keyboard, and refuse moves that break data flow", async ({ page }) => {
  await loginAsAdmin(page);
  page.on("dialog", (d) => d.accept());

  await page.goto("/admin/recipes");
  await page.getByRole("button", { name: "New recipe" }).click();
  await page.locator("#rc-name").fill(recipeName);
  await page.getByRole("button", { name: "Create and open builder" }).click();
  await page.getByTestId("try-studio").click();

  const cards = page.getByTestId("studio-card");
  const note = page.getByTestId("studio-note");
  const handle = (n: number) => cards.nth(n).getByTestId("drag-handle");

  // three log steps with distinct messages: s1 = A, s2 = B, s3 = C
  await page.getByRole("button", { name: "Add a step", exact: true }).first().click();
  await page.getByRole("menuitem", { name: "Write to the job log", exact: true }).click();
  await page.getByLabel("Message", { exact: true }).fill("A");
  for (const [n, text] of [[1, "{{steps.s1.output.message}} B"], [2, "C"]] as const) {
    await page.getByTestId("studio-add").nth(n).click();
    await page.getByRole("menuitem", { name: "Write to the job log", exact: true }).click();
    await page.getByLabel("Message", { exact: true }).fill(text);
  }
  await expect(cards).toHaveCount(3);

  // mouse: drag C to the top  ->  C, A, B
  await dragTo(page, handle(2), "steps|||0");
  await expect(cards.nth(0)).toContainText("C");
  await expect(cards.nth(1)).toContainText("A");

  // keyboard: Alt+Down on C  ->  A, C, B
  await handle(0).focus();
  await page.keyboard.press("Alt+ArrowDown");
  await expect(cards.nth(0)).toContainText("A");
  await expect(cards.nth(1)).toContainText("C");
  await expect(handle(1)).toBeFocused();

  // B reads A's output, so a drop near the end snaps to the nearest position that keeps A before B: C, A, B
  await dragTo(page, handle(0), "steps|||3");
  await expect(cards.nth(0)).toContainText("C");
  await expect(cards.nth(1)).toContainText("A");
  await expect(cards.nth(2)).toContainText("steps.s1");

  // undo puts it back: A, C, B
  await page.waitForTimeout(400);                       // the drop animation briefly covers the toolbar
  await page.getByRole("button", { name: "Undo" }).click();
  await expect(cards.nth(0)).toContainText("A");

  // nest C inside a new if/else; dropping the if/else on its own branch is never accepted
  await page.getByTestId("studio-add").nth(3).click();
  await page.getByRole("menuitem", { name: "If / else", exact: true }).click();
  await expect(cards).toHaveCount(4);
  await dragTo(page, handle(1), "steps|s4|then|0");
  const ifElse = page.getByTestId("studio-card").filter({ hasText: "If / else" }).first();
  await expect(ifElse.getByTestId("studio-card")).toHaveCount(1);
  await dragTo(page, ifElse.getByTestId("drag-handle").first(), "steps|s4|else|0");
  await expect(page.getByTestId("studio-card").filter({ hasText: "If / else" }).first().getByTestId("studio-card")).toHaveCount(1);
  await expect(page.getByTestId("studio-card")).toHaveCount(4);

  // clean up (nothing was saved)
  await page.goto("/admin/recipes");
  const row = page.getByTestId("recipes-table").locator("tr", { hasText: recipeName });
  await row.getByRole("button", { name: "Delete" }).click();
  await expect(page.getByTestId("recipes-table")).not.toContainText(recipeName);
});
