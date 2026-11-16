import { expect, test, type Page } from "@playwright/test";
import { ADMIN_EMAIL, ADMIN_PASSWORD, passSecondStep } from "./helpers";

// IFORA-42: the sign-in, add-user and add-app flows work with the keyboard alone, and focus is always visible.

/** "" when the focused control shows a focus indicator, otherwise a description of it for the failure message. */
async function focusProblem(page: Page): Promise<string> {
  return page.evaluate(() => {
    const el = document.activeElement as HTMLElement | null;
    if (el?.tagName === "NEXTJS-PORTAL") return ""; // the Next.js development overlay, not part of the app
    if (!el || el === document.body) return "focus is on the page body";
    const s = getComputedStyle(el);
    const ring = (s.outlineStyle !== "none" && parseFloat(s.outlineWidth) > 0) || s.boxShadow !== "none";
    return ring ? "" : el.outerHTML.slice(0, 160);
  });
}

async function tabTo(page: Page, match: (el: Element) => boolean, max = 150) {
  for (let i = 0; i < max; i++) {
    await page.keyboard.press("Tab");
    const problem = await focusProblem(page);
    if (problem === "focus is on the page body") continue; // Tab left the page into the browser; the next press comes back
    expect(problem, "the focused control has a visible focus indicator").toBe("");
    if (await page.evaluate(`(${match.toString()})(document.activeElement)`)) return;
  }
  throw new Error("control not reachable with Tab");
}

test("sign in with the keyboard only", async ({ page }) => {
  await page.goto("/login");
  await tabTo(page, (el) => (el as HTMLInputElement).id === "email");
  await page.keyboard.type(ADMIN_EMAIL);
  await page.keyboard.press("Tab");
  await page.keyboard.type(ADMIN_PASSWORD);
  await tabTo(page, (el) => /sign in/i.test((el as HTMLElement).innerText ?? "") && el.tagName === "BUTTON");
  await page.keyboard.press("Enter");
  await passSecondStep(page);
  await expect(page).toHaveURL(/\/admin\/dashboard/);
});

test("add a user with the keyboard only", async ({ page }) => {
  await page.goto("/login");
  await page.locator("#email").fill(ADMIN_EMAIL);
  await page.locator("#password").fill(ADMIN_PASSWORD);
  await page.keyboard.press("Enter");
  await passSecondStep(page);
  await page.goto("/admin/users");
  await tabTo(page, (el) => /new user/i.test((el as HTMLElement).innerText ?? "") && el.tagName === "BUTTON");
  await page.keyboard.press("Enter");
  await expect(page.getByRole("button", { name: "Create user" })).toBeVisible();
  // every field of the form is reachable, in reading order, and labelled
  const labels: string[] = [];
  for (let i = 0; i < 30; i++) {
    await page.keyboard.press("Tab");
    expect(await focusProblem(page), "the focused control has a visible focus indicator").toBe("");
    const name = await page.evaluate(() => {
      const el = document.activeElement as HTMLInputElement;
      return el.getAttribute("aria-label") || el.labels?.[0]?.innerText || el.innerText || "";
    });
    labels.push(name.trim());
    if (/create user/i.test(name)) break;
  }
  expect(labels.some((l) => /create user/i.test(l)), `reached Create user via Tab: ${labels.join(" | ")}`).toBe(true);
  expect(labels.filter((l) => !l).length, `unlabelled stops: ${labels.join(" | ")}`).toBe(0);
});

test("the command palette opens with the keyboard and traps focus", async ({ page }) => {
  await page.goto("/login");
  await page.locator("#email").fill(ADMIN_EMAIL);
  await page.locator("#password").fill(ADMIN_PASSWORD);
  await page.keyboard.press("Enter");
  await passSecondStep(page);
  await page.keyboard.press("Control+k");
  const dialog = page.getByRole("dialog", { name: "Search" });
  await expect(dialog).toBeVisible();
  await expect(page.getByRole("combobox", { name: "Search" })).toBeFocused();
  for (let i = 0; i < 4; i++) await page.keyboard.press("Tab");
  expect(await page.evaluate(() => !!document.activeElement?.closest("[role=dialog]")), "focus stays inside the dialog").toBe(true);
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
});
