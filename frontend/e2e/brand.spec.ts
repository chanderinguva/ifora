import { expect, test } from "@playwright/test";

const color = (loc: import("@playwright/test").Locator) => loc.evaluate((el) => getComputedStyle(el).color);
const rgb = (s: string) => s.match(/\d+/g)!.slice(0, 3).map(Number);

test("brand: Ifora gateway mark follows the theme, wordmark stays Lora, UI text is Inter, favicon and manifest are served", async ({ page, request }) => {
  // The product default brand, whatever this tenant has uploaded: serve the default branding to the page.
  await page.route("**/api/v1/branding", (route) =>
    route.fulfill({ json: { display_name: "Ifora", custom_name: false, primary_color: null, tagline: null, has_logo: false, logo_rev: null } }),
  );
  await page.emulateMedia({ colorScheme: "light" });
  await page.goto("/login");
  const mark = page.getByTestId("logo-mark").first();
  const wordmark = page.getByTestId("logo-wordmark");
  await expect(mark).toBeVisible();
  await expect(wordmark).toHaveText("Ifora");

  // theme: the mark uses the Ifora tokens (indigo/blue/violet on light, lighter tints on dark); wordmark is navy / cloud
  const fills = (svg: import("@playwright/test").Locator) => svg.evaluate((el) => [...el.querySelectorAll("path,circle")].map((n) => getComputedStyle(n).fill));
  await page.getByTestId("theme-toggle").getByRole("radio", { name: "Light theme" }).click();
  expect(await fills(mark)).toEqual(["rgb(79, 70, 229)", "rgb(37, 99, 235)", "rgb(139, 92, 246)"]);
  expect(rgb(await color(wordmark))[0]).toBeLessThan(40);
  await page.getByTestId("theme-toggle").getByRole("radio", { name: "Dark theme" }).click();
  await expect(page.locator("html")).toHaveClass(/dark/);
  expect(await fills(mark)).toEqual(["rgb(129, 140, 248)", "rgb(96, 165, 250)", "rgb(167, 139, 250)"]);
  expect(rgb(await color(wordmark))[0]).toBeGreaterThan(215);

  // typography: the wordmark is live Lora text, not an image or a fallback font
  const family = await wordmark.evaluate((el) => getComputedStyle(el).fontFamily);
  expect(family).toMatch(/lora/i);
  const bodyFamily = await page.evaluate(() => getComputedStyle(document.body).fontFamily);
  expect(bodyFamily).toMatch(/inter/i);
  await page.evaluate(() => document.fonts.ready);
  expect(await page.evaluate(() => document.fonts.check("600 18px Lora"))).toBe(true);

  // favicon + manifest + apple icon are wired and actually served
  const links = await page.evaluate(() => [...document.querySelectorAll("link[rel~=icon], link[rel=apple-touch-icon], link[rel=manifest]")].map((l) => (l as HTMLLinkElement).href));
  expect(links.some((h) => h.endsWith("/icon.svg") || h.includes("/icon.svg?"))).toBe(true);
  expect(links.some((h) => h.includes("favicon.ico"))).toBe(true);
  expect(links.some((h) => h.includes("apple-icon"))).toBe(true);
  for (const path of ["/icon.svg", "/favicon.ico", "/apple-icon.png", "/manifest.webmanifest", "/icons/icon-512.png", "/icons/icon-maskable-512.png"]) {
    const r = await request.get(path);
    expect(r.status(), path).toBe(200);
  }
  const svg = await (await request.get("/icon.svg")).text();
  expect(svg).toContain("prefers-color-scheme: dark");
  expect(svg).not.toMatch(/<script|https?:\/\/(?!www\.w3\.org)/i);
});
