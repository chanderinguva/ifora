import { expect, test } from "@playwright/test";

const bg = (page: import("@playwright/test").Page) =>
  page.evaluate(() => getComputedStyle(document.body).backgroundColor);

test("dark theme: toggle, persistence, and following the system setting", async ({ page }) => {
  await page.emulateMedia({ colorScheme: "light" });
  await page.goto("/login");
  const html = page.locator("html");
  const toggle = page.getByTestId("theme-toggle");
  await expect(toggle).toBeVisible();

  // explicit light
  await toggle.getByRole("radio", { name: "Light theme" }).click();
  await expect(html).not.toHaveClass(/dark/);
  expect(await bg(page)).toBe("rgb(246, 247, 248)");   // --background in globals.css (light graphite, hsl 220 12% 97%)

  // explicit dark: class, colours, form controls and card all switch
  await toggle.getByRole("radio", { name: "Dark theme" }).click();
  await expect(html).toHaveClass(/dark/);
  await expect(toggle.getByRole("radio", { name: "Dark theme" })).toHaveAttribute("aria-checked", "true");
  const dark = await bg(page);
  expect(dark).not.toBe("rgb(255, 255, 255)");
  const [r, g, b] = dark.match(/\d+/g)!.map(Number);
  expect(r + g + b).toBeLessThan(120);
  const cardBg = await page.locator("form").first().evaluate((el) => getComputedStyle(el.closest("[class*=rounded]")!).backgroundColor);
  expect(cardBg).not.toBe("rgb(255, 255, 255)");

  // persists across reloads without a light flash (class is set before hydration)
  await page.reload();
  await expect(html).toHaveClass(/dark/);

  // system follows the OS preference live
  await toggle.getByRole("radio", { name: "System theme" }).click();
  await page.emulateMedia({ colorScheme: "light" });
  await expect(html).not.toHaveClass(/dark/);
  await page.emulateMedia({ colorScheme: "dark" });
  await expect(html).toHaveClass(/dark/);
});
