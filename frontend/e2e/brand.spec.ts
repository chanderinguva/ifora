import { expect, test } from "@playwright/test";

const color = (loc: import("@playwright/test").Locator) => loc.evaluate((el) => getComputedStyle(el).color);
const rgb = (s: string) => s.match(/\d+/g)!.slice(0, 3).map(Number);

test("brand: forge-fold mark follows the theme, wordmark stays Lora, favicon and manifest are served", async ({ page, request }) => {
  await page.emulateMedia({ colorScheme: "light" });
  await page.goto("/login");
  const mark = page.getByTestId("logo-mark").first();
  const wordmark = page.getByTestId("logo-wordmark");
  await expect(mark).toBeVisible();
  await expect(wordmark).toHaveText("IdentityForge");

  // theme: near-black on light, near-white on dark, for both mark and wordmark
  await page.getByTestId("theme-toggle").getByRole("radio", { name: "Light theme" }).click();
  const [lr] = rgb(await color(mark));
  expect(lr).toBeLessThan(40);
  await page.getByTestId("theme-toggle").getByRole("radio", { name: "Dark theme" }).click();
  await expect(page.locator("html")).toHaveClass(/dark/);
  const [dr] = rgb(await color(mark));
  expect(dr).toBeGreaterThan(215);
  expect(rgb(await color(wordmark))[0]).toBeGreaterThan(215);

  // the paint really is currentColor (no hard-coded fills that would break in one theme)
  const paints = await mark.evaluate((svg) => [...svg.querySelectorAll("path,circle")].map((n) => n.getAttribute("stroke") ?? n.getAttribute("fill")));
  expect(paints).toEqual(["currentColor", "currentColor", "currentColor"]);

  // typography: the wordmark is live Lora text, not an image or a fallback font
  const family = await wordmark.evaluate((el) => getComputedStyle(el).fontFamily);
  expect(family).toMatch(/lora/i);
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
