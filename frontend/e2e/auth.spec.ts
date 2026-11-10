import { expect, test } from "@playwright/test";
import { login, loginAsAdmin, logout } from "./helpers";

test("unauthenticated visitors are sent to the login page", async ({ page }) => {
  for (const path of ["/", "/admin/dashboard", "/admin/users", "/dashboard"]) {
    await page.goto(path);
    await expect(page).toHaveURL(/\/login/);
  }
});

test("bad credentials show a generic error and stay on login", async ({ page }) => {
  // unknown email on purpose: avoids locking the real admin account
  await login(page, "nobody-e2e@example.com", "WrongPassw0rd!!");
  await expect(page.getByText("Invalid credentials")).toBeVisible();
  await expect(page).toHaveURL(/\/login/);
});

test("admin signs in, sees real stats, session cookie is HttpOnly, and logs out", async ({ page, context }) => {
  await loginAsAdmin(page);
  const stats = page.getByTestId("stats");
  await expect(stats).toContainText("Users");
  const users = Number(await page.getByTestId("stat-Users").innerText());
  expect(users).toBeGreaterThanOrEqual(1);

  const cookie = (await context.cookies()).find((c) => c.name === "identityforge_session");
  expect(cookie?.httpOnly).toBe(true);
  expect(cookie?.sameSite).toBe("Lax");
  expect(await page.evaluate(() => document.cookie)).not.toContain("identityforge_session");

  await logout(page);
  await page.goto("/admin/dashboard");
  await expect(page).toHaveURL(/\/login/);
});

test("the app UI renders in Inter and the wordmark in Lora", async ({ page }) => {
  await loginAsAdmin(page);
  for (const sel of ["body", "h1", "button"]) {
    const family = await page.locator(sel).first().evaluate((el) => getComputedStyle(el).fontFamily);
    expect(family).toContain("Inter");
  }
  const wordmark = await page.getByTestId("logo-wordmark").first().evaluate((el) => getComputedStyle(el).fontFamily);
  expect(wordmark).toContain("Lora");
  const loaded = await page.evaluate(() => ["Inter", "Lora"].every((n) => [...document.fonts].some((f) => f.family.includes(n) && f.status === "loaded")));
  expect(loaded).toBe(true);
});
