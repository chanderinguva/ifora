import { expect, test, type Page } from "@playwright/test";
import { USER_PASSWORD, loginAsAdmin } from "./helpers";

const API = "http://localhost:8000/api/v1";

async function api(page: Page, method: string, path: string, body?: unknown) {
  return page.evaluate(async ([m, p, b, base]) => {
    const me = await (await fetch(`${base}/me`, { credentials: "include" })).json();
    const r = await fetch(`${base}${p}`, { method: m as string, credentials: "include", headers: { "Content-Type": "application/json", "X-CSRF-Token": me.csrf_token }, body: b ? JSON.stringify(b) : undefined });
    return { status: r.status, json: r.status === 204 ? null : await r.json().catch(() => null) };
  }, [method, path, body, API] as const);
}

// Nobody signs in as the new users, so this runs with ADMIN_MFA_REQUIRED either way.
test("the Users list can be filtered by role", async ({ page }) => {
  const tag = Date.now();
  const ids: number[] = [];
  await loginAsAdmin(page);
  try {
    const admin = (await api(page, "POST", "/admin/users", { email: `rf.admin.${tag}@example.com`, first_name: "Rf", last_name: `Admin${tag}`, password: USER_PASSWORD, is_admin: true })).json;
    const regular = (await api(page, "POST", "/admin/users", { email: `rf.user.${tag}@example.com`, first_name: "Rf", last_name: `User${tag}`, password: USER_PASSWORD, is_admin: false })).json;
    ids.push(admin.id, regular.id);

    await page.goto("/admin/users");
    await page.getByPlaceholder("Search name, email or username").fill(`rf.`);
    const rows = page.getByRole("row");
    await expect(rows.filter({ hasText: `Admin${tag}` })).toHaveCount(1);
    await expect(rows.filter({ hasText: `User${tag}` })).toHaveCount(1);

    const filter = page.getByLabel("Filter by role");
    await filter.selectOption({ label: "Not an administrator" });
    await expect(rows.filter({ hasText: `User${tag}` })).toHaveCount(1);
    await expect(rows.filter({ hasText: `Admin${tag}` })).toHaveCount(0);

    // a new administrator starts as a read-only administrator
    await filter.selectOption({ label: "Read-only administrator" });
    await expect(rows.filter({ hasText: `Admin${tag}` })).toHaveCount(1);
    await expect(rows.filter({ hasText: `User${tag}` })).toHaveCount(0);

    await filter.selectOption({ label: "Report administrator" });
    await expect(rows.filter({ hasText: `Admin${tag}` })).toHaveCount(0);
  } finally {
    for (const id of ids) await api(page, "DELETE", `/admin/users/${id}`);
  }
});
