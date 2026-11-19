import { expect, test } from "@playwright/test";

const bg = (page: import("@playwright/test").Page) =>
  page.evaluate(() => getComputedStyle(document.body).backgroundColor);

/** Open the theme dropdown and pick one. */
async function choose(page: import("@playwright/test").Page, label: string) {
  const toggle = page.getByTestId("theme-toggle");
  await toggle.getByRole("button", { name: /^Colour theme/ }).click();
  await toggle.getByRole("radio", { name: `${label} theme` }).click();
  await expect(toggle.getByRole("radiogroup")).toHaveCount(0); // closes after choosing
}

test("dark theme: toggle, persistence, and following the system setting", async ({ page }) => {
  await page.emulateMedia({ colorScheme: "light" });
  await page.goto("/login");
  const html = page.locator("html");
  const toggle = page.getByTestId("theme-toggle");
  await expect(toggle).toBeVisible();

  // explicit light
  await choose(page, "Light");
  await expect(html).not.toHaveClass(/dark/);
  expect(await bg(page)).toBe("rgb(246, 247, 248)");   // --background in globals.css (light graphite, hsl 220 12% 97%)

  // explicit dark: class, colours, form controls and card all switch
  await choose(page, "Dark");
  await expect(html).toHaveClass(/dark/);
  await expect(toggle.getByRole("button", { name: "Colour theme: Dark" })).toBeVisible();
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
  await choose(page, "System");
  await page.emulateMedia({ colorScheme: "light" });
  await expect(html).not.toHaveClass(/dark/);
  await page.emulateMedia({ colorScheme: "dark" });
  await expect(html).toHaveClass(/dark/);
});

test("theme menu is one compact button; Escape and outside click close it; arrows move; selected theme is marked", async ({ page }) => {
  await page.goto("/login");
  const toggle = page.getByTestId("theme-toggle");
  const button = toggle.getByRole("button", { name: /^Colour theme/ });
  expect((await button.boundingBox())!.width).toBeLessThanOrEqual(40);
  await expect(toggle.getByRole("radio")).toHaveCount(0);

  await button.click();
  await expect(toggle.getByRole("radio")).toHaveCount(7);
  await page.keyboard.press("Escape");
  await expect(toggle.getByRole("radiogroup")).toHaveCount(0);
  await expect(button).toBeFocused();

  await button.click();
  await page.mouse.click(5, 400);
  await expect(toggle.getByRole("radiogroup")).toHaveCount(0);

  await choose(page, "Midnight");
  await button.click();
  await expect(toggle.getByRole("radio", { name: "Midnight theme" })).toHaveAttribute("aria-checked", "true");
  await expect(toggle.getByRole("radio", { name: "Midnight theme" })).toBeFocused();
  await page.keyboard.press("ArrowDown");
  await expect(toggle.getByRole("radio", { name: "Forest theme" })).toBeFocused();
});

for (const [name, cls, dark] of [["Sand", "sand", false], ["Ocean", "ocean", false], ["Midnight", "midnight", true], ["Forest", "forest", true]] as const) {
  test(`${name} theme applies, differs from light/dark, and persists across reloads`, async ({ page }) => {
    await page.emulateMedia({ colorScheme: "light" });
    await page.goto("/login");
    await choose(page, "Light");
    const light = await bg(page);
    await choose(page, name);
    await expect(page.locator("html")).toHaveClass(new RegExp(`\\b${cls}\\b`));
    await expect(page.getByTestId("theme-toggle").getByRole("button", { name: `Colour theme: ${name}` })).toBeVisible();
    const themed = await bg(page);
    expect(themed).not.toBe(light);
    const [r, g, b] = themed.match(/\d+/g)!.map(Number);
    if (dark) expect(r + g + b).toBeLessThan(120);
    else expect(r + g + b).toBeGreaterThan(600);
    await page.reload();
    await expect(page.locator("html")).toHaveClass(new RegExp(`\\b${cls}\\b`));
    expect(await bg(page)).toBe(themed);
  });
}
