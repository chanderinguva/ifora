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
test("the user page has a Groups and Roles tab: groups with their type, effective roles with their source, and notes for non-administrators", async ({ page }) => {
  const tag = Date.now();
  const plainGroup = `E2E Plain ${tag}`;
  const teamGroup = `Team - E2E Roles ${tag}`;
  await loginAsAdmin(page);
  const me = (await api(page, "GET", "/me")).json.user;
  const ids = { users: [] as number[], groups: [] as number[] };
  try {
    const plain = (await api(page, "POST", "/admin/groups", { name: plainGroup, type: "other" })).json;
    const team = (await api(page, "POST", "/admin/groups", { name: teamGroup, type: "team", owner_user_id: me.id })).json;
    ids.groups.push(plain.id, team.id);
    expect((await api(page, "PUT", `/admin/roles/groups/${team.id}`, { roles: ["help_desk_admin"] })).status).toBe(200);

    const admin = (await api(page, "POST", "/admin/users", { email: `ugr.admin.${tag}@example.com`, first_name: "Ugr", last_name: `Admin${tag}`, password: USER_PASSWORD, is_admin: true, group_ids: [plain.id, team.id] })).json;
    const regular = (await api(page, "POST", "/admin/users", { email: `ugr.user.${tag}@example.com`, first_name: "Ugr", last_name: `User${tag}`, password: USER_PASSWORD, is_admin: false })).json;
    ids.users.push(admin.id, regular.id);

    // an administrator: both groups with their type, the direct default role and the role that arrives through the team group
    await page.goto(`/admin/users/${admin.id}`);
    await page.getByTestId("utab-access").click();
    const groups = page.getByTestId("user-groups");
    await expect(groups).toContainText("Groups (2)");
    await expect(groups.getByTestId("user-group-row").filter({ hasText: plainGroup })).toContainText("other");
    await expect(groups.getByTestId("user-group-row").filter({ hasText: teamGroup })).toContainText("team");
    await expect(groups.getByRole("link", { name: teamGroup })).toHaveAttribute("href", `/admin/groups/${team.id}`);
    const effective = page.getByTestId("effective-roles");
    await expect(effective.getByTestId("role-via-read_only_admin")).toContainText("assigned directly");
    await expect(effective.getByTestId("role-via-help_desk_admin")).toContainText(`through ${teamGroup}`);

    // the profile tab no longer carries the groups or roles cards
    await page.getByTestId("utab-profile").click();
    await expect(page.getByTestId("user-groups")).toHaveCount(0);
    await expect(page.getByTestId("admin-roles")).toHaveCount(0);

    // someone who is not an administrator: no groups, and a note instead of the role checkboxes
    await page.goto(`/admin/users/${regular.id}`);
    await page.getByTestId("utab-access").click();
    await expect(page.getByTestId("user-groups")).toContainText("Not a member of any group");
    await expect(page.getByTestId("user-roles-note")).toContainText("not an administrator");
  } finally {
    for (const id of ids.users) await api(page, "DELETE", `/admin/users/${id}`);
    for (const id of ids.groups) await api(page, "DELETE", `/admin/groups/${id}`);
  }
});
