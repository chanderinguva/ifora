import { expect, test, type Page } from "@playwright/test";
import { login, logout } from "./helpers";

// Throwaway admin, backend with ADMIN_MFA_REQUIRED=false (see role-switch.spec.ts).
const email = process.env.E2E_ROLE_ADMIN_EMAIL ?? "";
const password = process.env.E2E_ROLE_ADMIN_PASSWORD ?? "";
test.skip(!email || !password, "set E2E_ROLE_ADMIN_EMAIL / E2E_ROLE_ADMIN_PASSWORD for a throwaway admin");

const main = (p: Page) => p.getByRole("navigation", { name: "Main" });

test.describe("desktop shell", () => {
  test("logo links home, nav is grouped, breadcrumbs follow the page", async ({ page }) => {
    await login(page, email, password);
    await expect(page).toHaveURL(/\/admin\/dashboard/);

    // logo + name is a link home (NN/g: the top-left logo is the home link)
    const home = page.getByRole("link", { name: "IdentityForge home" }).first();
    await expect(home).toHaveAttribute("href", "/admin/dashboard");
    await expect(page.getByTestId("logo-wordmark").first()).toBeVisible();

    // labelled groups, current page marked
    const nav = main(page);
    await expect(nav.getByText("Directory")).toBeVisible();
    await expect(nav.getByText("Security")).toBeVisible();
    await expect(nav.getByRole("link", { name: "Dashboard" })).toHaveAttribute("aria-current", "page");

    // breadcrumbs: current page, then a trail with a working link back
    const crumbs = page.getByRole("navigation", { name: "Breadcrumb" });
    await expect(crumbs).toContainText("Dashboard");
    await nav.getByRole("link", { name: "Users" }).click();
    await expect(crumbs.getByText("Users")).toHaveAttribute("aria-current", "page");
    await page.getByTestId("users-table").getByRole("link").first().click();
    await expect(crumbs).toContainText("Details");
    await crumbs.getByRole("link", { name: "Users" }).click();
    await expect(page).toHaveURL(/\/admin\/users$/);

    // the logo takes you home from anywhere
    await home.click();
    await expect(page).toHaveURL(/\/admin\/dashboard/);
    await logout(page);
  });

  test("sidebar collapses to an icon rail with accessible names, tooltips and persistence", async ({ page }) => {
    await login(page, email, password);
    const aside = page.locator("#sidebar");
    const toggle = page.getByTestId("toggle-sidebar");
    await expect(aside).toHaveAttribute("data-collapsed", "false");
    await expect(toggle).toHaveAttribute("aria-expanded", "true");
    const wide = (await aside.boundingBox())!.width;

    await toggle.click();
    await expect(aside).toHaveAttribute("data-collapsed", "true");
    await expect(toggle).toHaveAttribute("aria-label", "Expand sidebar");
    await expect.poll(async () => (await aside.boundingBox())!.width).toBeLessThan(wide / 2);
    // wordmark and group labels are gone, the mark stays, and every item keeps its accessible name
    await expect(aside.getByTestId("logo-wordmark")).toHaveCount(0);
    await expect(aside.getByTestId("logo-mark")).toBeVisible();
    await expect(aside.getByRole("link", { name: "IdentityForge home" })).toBeVisible();
    const users = main(page).getByRole("link", { name: "Users" });
    await expect(users).toBeVisible();

    // tooltip appears on keyboard focus, not just hover
    const tip = users.locator("span[aria-hidden=true]").last();
    await expect(tip).toHaveCSS("opacity", "0");
    // keyboard modality (a scripted focus after a mouse click does not match :focus-visible)
    await users.focus();
    await page.keyboard.press("Shift+Tab");
    await page.keyboard.press("Tab");
    await expect(users).toBeFocused();
    await expect(tip).toHaveCSS("opacity", "1");
    await expect(tip).toHaveText("Users");

    // persisted across reloads, and reversible
    await page.reload();
    await expect(aside).toHaveAttribute("data-collapsed", "true");
    await page.getByTestId("toggle-sidebar").click();
    await expect(aside).toHaveAttribute("data-collapsed", "false");
    await logout(page);
  });

  test("skip link jumps to the main content", async ({ page }) => {
    await login(page, email, password);
    await expect(page).toHaveURL(/\/admin\/dashboard/);
    await expect(page.getByTestId("user-menu")).toBeVisible(); // shell rendered (session check done)
    await page.keyboard.press("Tab");
    const skip = page.getByRole("link", { name: "Skip to main content" });
    await expect(skip).toBeFocused();
    await expect(skip).toBeVisible();
    await page.keyboard.press("Enter");
    await expect(page.locator("#main")).toBeFocused();
    await logout(page);
  });
});

test.describe("mobile shell", () => {
  test.use({ viewport: { width: 390, height: 800 } });

  test("sidebar becomes an accessible drawer; page does not scroll sideways", async ({ page }) => {
    await login(page, email, password);
    await expect(page).toHaveURL(/\/admin\/dashboard/);
    await expect(page.locator("#sidebar")).toBeHidden();
    const open = page.getByTestId("open-nav");
    await expect(open).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);

    // open: dialog, focus moves in, scroll locked
    await open.click();
    const drawer = page.getByTestId("mobile-drawer");
    await expect(drawer).toBeVisible();
    await expect(drawer.getByRole("link", { name: "IdentityForge home" })).toBeFocused();
    await expect(drawer.getByText("Directory")).toBeVisible();
    // Escape closes and returns focus to the button that opened it
    await page.keyboard.press("Escape");
    await expect(drawer).toBeHidden();
    await expect(open).toBeFocused();

    // backdrop closes
    await open.click();
    await page.mouse.click(380, 400);
    await expect(drawer).toBeHidden();

    // choosing a destination navigates and closes
    await open.click();
    await drawer.getByRole("link", { name: "Users" }).click();
    await expect(page).toHaveURL(/\/admin\/users$/);
    await expect(drawer).toBeHidden();

    // Tab stays inside the open drawer
    await open.click();
    for (let i = 0; i < 12; i++) await page.keyboard.press("Tab");
    expect(await page.evaluate(() => !!document.activeElement?.closest("[data-testid=mobile-drawer]"))).toBe(true);
    await page.keyboard.press("Escape");
    await logout(page);
  });
});
