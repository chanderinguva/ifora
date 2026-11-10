import { expect, test, type Page } from "@playwright/test";
import { USER_PASSWORD, login, loginAsAdmin, logout } from "./helpers";

const API = "http://localhost:8000/api/v1";

async function api(page: Page, method: string, path: string, body?: unknown) {
  return page.evaluate(async ([m, p, b, base]) => {
    const me = await (await fetch(`${base}/me`, { credentials: "include" })).json();
    const r = await fetch(`${base}${p}`, { method: m as string, credentials: "include", headers: { "Content-Type": "application/json", "X-CSRF-Token": me.csrf_token }, body: b ? JSON.stringify(b) : undefined });
    return { status: r.status, json: r.status === 204 ? null : await r.json().catch(() => null) };
  }, [method, path, body, API] as const);
}

test("administrator roles are granted through a team group", async ({ page }) => {
  const tag = Date.now();
  const email = `grp.admin.${tag}@example.com`;
  const groupName = `Team - E2E Support ${tag}`;
  await loginAsAdmin(page);
  const user = (await api(page, "POST", "/admin/users", { email, first_name: "Grp", last_name: `A${tag}`, password: USER_PASSWORD, is_admin: true })).json;
  await api(page, "PUT", `/admin/roles/users/${user.id}`, { roles: [] });   // starts with no role of its own
  let groupId: number | null = null;
  try {
    // create a team group from the UI
    await page.goto("/admin/groups");
    await page.getByRole("button", { name: /New group/ }).click();
    await page.getByLabel("Name", { exact: true }).fill(groupName);
    await page.locator("#gm-type").selectOption("team");
    await page.locator("#gm-owner").selectOption({ index: 1 });
    await page.locator("#gm-sens").selectOption("medium");
    await page.locator("#gm-tags").fill("support, tier-1");
    await page.getByRole("button", { name: "Create group" }).click();
    await page.getByLabel("Search groups").fill(`E2E Support ${tag}`);
    await page.getByRole("link", { name: groupName }).click();
    await expect(page).toHaveURL(/\/admin\/groups\/\d+/);
    groupId = Number(page.url().split("/").pop());

    // give the group the help desk role, add the person
    await page.getByTestId("group-role-help_desk_admin").check();
    await page.getByTestId("group-roles-save").click();
    await expect(page.getByTestId("group-roles")).toContainText("Roles saved");
    await page.getByLabel("User to add").selectOption({ label: `Grp A${tag} (${email})` });
    await page.getByRole("button", { name: "Add", exact: true }).click();
    await expect(page.getByTestId("members-table")).toContainText(email);

    // the user page shows where the role comes from
    await page.goto(`/admin/users/${user.id}`);
    await page.getByTestId("utab-access").click();
    await expect(page.getByTestId("user-groups")).toContainText(groupName);
    await expect(page.getByTestId("role-via-help_desk_admin")).toContainText(groupName);
    await logout(page);

    // the person can now use the help desk functions, and nothing more
    await login(page, email, USER_PASSWORD);
    await expect(page).toHaveURL(/\/admin\/dashboard/);
    expect((await api(page, "GET", "/admin/users")).status).toBe(200);
    expect((await api(page, "POST", "/admin/groups", { name: `nope ${tag}` })).status).toBe(403);
    await logout(page);

    // leaving the group takes the role away, with no fall back to full access
    await loginAsAdmin(page);
    await api(page, "DELETE", `/admin/groups/${groupId}/members/${user.id}`);
    await logout(page);
    await login(page, email, USER_PASSWORD);
    expect((await api(page, "GET", "/admin/users")).status).toBe(403);
    await logout(page);

    await loginAsAdmin(page);
    await page.goto("/admin/groups");
    await expect(page.getByTestId("group-analytics")).toContainText("groups");
  } finally {
    if (page.url().includes("/login")) await loginAsAdmin(page);
    if (groupId) await api(page, "DELETE", `/admin/groups/${groupId}`);
    await api(page, "DELETE", `/admin/users/${user.id}`);
  }
});
