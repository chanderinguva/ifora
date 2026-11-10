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

// Nobody signs in as the new records, so this runs with ADMIN_MFA_REQUIRED either way.
test("Save only appears once something changed: user, group, branding and roles", async ({ page }) => {
  const tag = Date.now();
  const ids = { users: [] as number[], groups: [] as number[] };
  await loginAsAdmin(page);
  const me = (await api(page, "GET", "/me")).json.user;
  try {
    const user = (await api(page, "POST", "/admin/users", { email: `ds.user.${tag}@example.com`, first_name: "Ds", last_name: `User${tag}`, password: USER_PASSWORD, is_admin: true })).json;
    const group = (await api(page, "POST", "/admin/groups", { name: `Team - DS ${tag}`, type: "team", owner_user_id: me.id })).json;
    ids.users.push(user.id); ids.groups.push(group.id);

    // user page: no button until a field changes, none again when the change is put back, gone after saving
    await page.goto(`/admin/users/${user.id}`);
    const first = page.locator("#first");
    await expect(first).toHaveValue("Ds");
    const save = page.getByRole("button", { name: "Save changes" });
    await expect(save).toHaveCount(0);
    await first.fill("Dsx");
    await expect(save).toBeVisible();
    await first.fill("Ds");
    await expect(save).toHaveCount(0);
    await first.fill("Dsy");
    await save.click();
    await expect(page.getByText("Saved", { exact: true })).toBeVisible();
    await expect(save).toHaveCount(0);
    await page.reload();
    await expect(page.locator("#first")).toHaveValue("Dsy");
    await expect(save).toHaveCount(0);

    // the roles card on the Groups and Roles tab behaves the same
    await page.getByTestId("utab-access").click();
    const roleSave = page.getByTestId("roles-save");
    await expect(page.getByTestId("admin-roles")).toBeVisible();
    await expect(roleSave).toHaveCount(0);
    await page.getByTestId("role-help_desk_admin").check();
    await expect(roleSave).toBeVisible();
    await page.getByTestId("role-help_desk_admin").uncheck();
    await expect(roleSave).toHaveCount(0);

    // group page
    await page.goto(`/admin/groups/${group.id}`);
    const gname = page.locator("#gname");
    await expect(gname).toHaveValue(`Team - DS ${tag}`);
    await expect(page.getByRole("button", { name: "Save changes" })).toHaveCount(0);
    await page.locator("#gdesc").fill("a description");
    await expect(page.getByRole("button", { name: "Save changes" })).toBeVisible();
    await page.getByRole("button", { name: "Save changes" }).click();
    await expect(page.getByRole("button", { name: "Save changes" })).toHaveCount(0);
    await expect(page.locator("#gdesc")).toHaveValue("a description");
    await expect(page.getByTestId("group-roles-save")).toHaveCount(0);

    // branding
    await page.goto("/admin/branding");
    await expect(page.locator("#b-name")).toBeVisible();
    await expect(page.getByTestId("branding-save")).toHaveCount(0);
    await page.locator("#b-tag").fill(`hello ${tag}`);
    await expect(page.getByTestId("branding-save")).toBeVisible();
    await page.locator("#b-tag").fill("");
    await expect(page.getByTestId("branding-save")).toHaveCount(0);
  } finally {
    for (const id of ids.users) await api(page, "DELETE", `/admin/users/${id}`);
    for (const id of ids.groups) await api(page, "DELETE", `/admin/groups/${id}`);
  }
});
