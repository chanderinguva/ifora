import { expect, test } from "@playwright/test";
import { loginAsAdmin } from "./helpers";

// Uses the bootstrap admin, so it runs with ADMIN_MFA_REQUIRED either way.
test("the account menu is an avatar, the sidebar resizes and remembers its width, nav is grouped, search is wide", async ({ page }) => {
  await page.setViewportSize({ width: 1400, height: 900 });
  await loginAsAdmin(page);
  await page.goto("/admin/dashboard");

  // avatar: initials only on screen, the account in the tooltip, accessible name and the dropdown header
  const menu = page.getByTestId("user-menu");
  await expect(menu).toBeVisible();
  const box = (await menu.boundingBox())!;
  expect(box.width).toBeLessThan(50);
  await expect(menu).toHaveAttribute("title", /@/);
  await expect(page.getByTestId("current-user")).toContainText("@");
  await menu.click();
  await expect(page.getByTestId("user-menu-header")).toContainText("@");
  await expect(page.getByRole("menuitem", { name: "Log out" })).toBeVisible();
  await page.keyboard.press("Escape");

  // grouped navigation: related pages sit under one heading
  const nav = page.getByRole("navigation", { name: "Main" });
  const security = nav.getByRole("list", { name: "Security" });
  await expect(security.getByRole("link", { name: "Roles" })).toBeVisible();
  await expect(security.getByRole("link", { name: "Administrators & API tokens" })).toBeVisible();
  await expect(nav.getByRole("list", { name: "Directory" }).getByRole("link", { name: "Group rules" })).toBeVisible();
  await expect(nav.getByRole("list", { name: "Reports" }).getByRole("link", { name: "System log" })).toBeVisible();

  // search: a wide field with a placeholder, not a small button
  const search = page.getByTestId("open-search");
  expect((await search.boundingBox())!.width).toBeGreaterThan(300);
  await expect(search).toContainText("Search users, groups, apps");

  // resizable sidebar: arrow keys on the handle, remembered across a reload, double-click resets
  const aside = page.locator("#sidebar");
  const handle = page.getByTestId("sidebar-resizer");
  const start = (await aside.boundingBox())!.width;
  await handle.focus();
  await page.keyboard.press("ArrowRight");
  await page.keyboard.press("ArrowRight");
  await expect.poll(async () => (await aside.boundingBox())!.width).toBeCloseTo(start + 32, -1);
  await page.reload();
  await expect.poll(async () => (await aside.boundingBox())!.width).toBeCloseTo(start + 32, -1);
  await page.getByTestId("sidebar-resizer").dblclick();
  await expect.poll(async () => (await aside.boundingBox())!.width).toBeCloseTo(240, -1);

  // dragging with the mouse
  const edge = (await aside.boundingBox())!;
  await page.mouse.move(edge.x + edge.width - 1, 300);
  await page.mouse.down();
  await page.mouse.move(edge.x + 330, 300, { steps: 5 });
  await page.mouse.up();
  await expect.poll(async () => (await aside.boundingBox())!.width).toBeGreaterThan(300);
  await page.getByTestId("sidebar-resizer").dblclick(); // leave the browser profile as we found it
});
