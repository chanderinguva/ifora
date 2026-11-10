import { expect, test, type Page } from "@playwright/test";
import { loginAsAdmin } from "./helpers";

const API = "http://localhost:8000/api/v1";

async function api(page: Page, method: string, path: string, body?: unknown) {
  return page.evaluate(async ([m, p, b, base]) => {
    const me = await (await fetch(`${base}/me`, { credentials: "include" })).json();
    const r = await fetch(`${base}${p}`, { method: m as string, credentials: "include", headers: { "Content-Type": "application/json", "X-CSRF-Token": me.csrf_token }, body: b ? JSON.stringify(b) : undefined });
    return { status: r.status, json: r.status === 204 ? null : await r.json().catch(() => null) };
  }, [method, path, body, API] as const);
}

// Nobody signs in as another user, so this runs with ADMIN_MFA_REQUIRED either way.
test("the Roles page: pick a team group for a role, see it listed, remove it; role based groups are offered too; other kinds are not", async ({ page }) => {
  const tag = Date.now();
  const teamName = `Team - E2E Roles page ${tag}`;
  const plainName = `E2E Plain roles page ${tag}`;
  const roleName = `Role - E2E Roles page ${tag}`;
  page.on("dialog", (d) => d.accept());
  await loginAsAdmin(page);
  const me = (await api(page, "GET", "/me")).json.user;
  const groupIds: number[] = [];
  try {
    const team = (await api(page, "POST", "/admin/groups", { name: teamName, type: "team", owner_user_id: me.id })).json;
    const plain = (await api(page, "POST", "/admin/groups", { name: plainName, type: "other" })).json;
    expect(team?.id, "team group created").toBeTruthy();
    const roleGroup = (await api(page, "POST", "/admin/groups", { name: roleName, type: "role", owner_user_id: me.id })).json;
    expect(roleGroup?.id, "role based group created").toBeTruthy();
    groupIds.push(team.id, plain.id, roleGroup.id);

    // in the sidebar, next to Users and Groups
    await page.goto("/admin/dashboard");
    await expect(page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Roles", exact: true })).toBeVisible();
    await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Roles", exact: true }).click();
    await expect(page).toHaveURL(/\/admin\/roles$/);
    const labels: Record<string, string> = {
      org_admin: "Organization administrator", read_only_admin: "Read-only administrator", help_desk_admin: "Help desk administrator",
      app_admin: "Application administrator", group_admin: "Group administrator", report_admin: "Report administrator",
    };
    for (const [id, label] of Object.entries(labels)) await expect(page.getByTestId(`role-card-${id}`)).toContainText(label);

    const card = page.getByTestId("role-card-help_desk_admin");
    const select = card.getByLabel("Add a group to Help desk administrator");

    // team and role based groups are offered, other kinds are not
    const options = await select.locator("option").allTextContents();
    expect(options.join("|")).toContain(teamName);
    expect(options.join("|")).toContain(roleName);
    expect(options.join("|")).not.toContain(plainName);

    // add the team group to the role
    await expect(card.getByRole("button", { name: "Add group to Help desk administrator" })).toBeDisabled();
    await select.selectOption({ label: `${teamName} (0)` });
    await card.getByRole("button", { name: "Add group to Help desk administrator" }).click();
    await expect(page.getByTestId("roles-msg")).toContainText("now holds Help desk administrator");
    await expect(card.getByTestId("role-holder-help_desk_admin").filter({ hasText: teamName })).toContainText("0 members");
    expect((await api(page, "GET", `/admin/roles/groups/${team.id}`)).json.roles).toEqual(["help_desk_admin"]);
    // it is no longer offered for that role, but still for another
    expect((await select.locator("option").allTextContents()).join("|")).not.toContain(teamName);
    expect((await page.getByTestId("role-card-report_admin").getByLabel("Add a group to Report administrator").locator("option").allTextContents()).join("|")).toContain(teamName);

    // remove it again
    await card.getByRole("button", { name: `Remove ${teamName} from Help desk administrator` }).click();
    await expect(page.getByTestId("roles-msg")).toContainText("no longer holds Help desk administrator");
    await expect(card.getByTestId("role-holder-help_desk_admin").filter({ hasText: teamName })).toHaveCount(0);
    expect((await api(page, "GET", `/admin/roles/groups/${team.id}`)).json.roles).toEqual([]);
  } finally {
    for (const id of groupIds) await api(page, "DELETE", `/admin/groups/${id}`);
  }
});
