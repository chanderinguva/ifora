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

test("a user requests an app, an administrator approves it, and it appears under My apps", async ({ page }) => {
  const tag = Date.now();
  const name = `Req app ${tag}`;
  const email = `req.${tag}@example.com`;
  await loginAsAdmin(page);
  const app = (await api(page, "POST", "/admin/applications", { name, sign_on_mode: "bookmark", launch_url: "https://example.com/e2e" })).json;
  const user = (await api(page, "POST", "/admin/users", { email, first_name: "Req", last_name: `T${tag}`, password: USER_PASSWORD })).json;
  let appId: number = app.id;
  try {
    // the switch lives on the application's General tab
    await page.goto(`/admin/applications/${appId}`);
    await page.getByTestId("self-service-enabled").check();
    await expect(page.getByTestId("self-service-card")).toContainText("Saved");
    await page.getByTestId("self-service-reason").check();
    await expect(page.getByTestId("self-service-reason")).toBeChecked();
    await logout(page);

    // the person asks
    await login(page, email, USER_PASSWORD);
    await page.goto("/apps/request");
    await page.getByRole("button", { name: `Request ${name}` }).click();
    await page.getByTestId("send-request").click();           // reason is required: the browser blocks an empty one
    await expect(page.getByTestId("catalog")).toContainText(name);
    await page.getByLabel(/Why do you need it/).fill("Onboarding to the team");
    await page.getByTestId("send-request").click();
    await expect(page.getByTestId("my-requests")).toContainText("pending");
    await page.goto("/apps");
    await expect(page.getByRole("button", { name: `Open ${name}` })).toHaveCount(0);   // asking grants nothing
    await logout(page);

    // the administrator decides
    await loginAsAdmin(page);
    await page.goto("/admin/access-requests");
    const row = page.locator("tr", { hasText: email });
    await expect(row).toContainText("Onboarding to the team");
    await row.getByLabel(`Note for ${email}`).fill("welcome");
    await row.getByRole("button", { name: /^Approve/ }).click();
    await expect(page.getByRole("status").first()).toContainText("Approved");
    await page.getByTestId("req-tab-approved").click();
    await expect(page.locator("tr", { hasText: email })).toContainText("approved");
    await logout(page);

    // now the tile is there
    await login(page, email, USER_PASSWORD);
    await page.goto("/apps");
    await expect(page.getByRole("button", { name: `Open ${name}` })).toBeVisible();
    await logout(page);
  } finally {
    await loginAsAdmin(page).catch(() => {});
    await api(page, "DELETE", `/admin/applications/${appId}`);
    if (user?.id) await api(page, "DELETE", `/admin/users/${user.id}`);
  }
});
