import { expect, test, type Page } from "@playwright/test";
import { loginAsAdmin } from "./helpers";

const API = "http://localhost:8000/api/v1";

async function api(page: Page, method: string, path: string, body?: unknown) {
  return page.evaluate(async ([m, p, b, base]) => {
    const me = await (await fetch(`${base}/me`, { credentials: "include" })).json();
    const r = await fetch(`${base}${p}`, { method: m as string, credentials: "include", headers: { "Content-Type": "application/json", "X-CSRF-Token": me.csrf_token }, body: b ? JSON.stringify(b) : undefined });
    return { status: r.status, json: r.status === 204 ? null : await r.json().catch(() => null), uid: me.user.id };
  }, [method, path, body, API] as const);
}

test("favourites, sections, recently used and recent activity on the user dashboard", async ({ page, context }) => {
  const tag = Date.now();
  const names = [`Zed ${tag}`, `Amy ${tag}`];
  const ids: number[] = [];
  await loginAsAdmin(page);
  for (const n of names) {
    const r = await api(page, "POST", "/admin/applications", { name: n, sign_on_mode: "bookmark", launch_url: "https://example.com/e2e" });
    expect(r.status).toBe(201);
    ids.push(r.json.id);
    expect((await api(page, "POST", `/admin/applications/${r.json.id}/assignments`, { user_id: r.uid })).status).toBe(201);
  }
  let sectionId: number | null = null;
  try {
    await page.goto("/dashboard");
    await expect(page.getByRole("button", { name: `Open ${names[0]}` })).toBeVisible();

    // favourite moves a tile into the Favourites group and survives a reload (stored on the account)
    await page.getByRole("button", { name: `Add ${names[0]} to favourites` }).click();
    await expect(page.getByTestId("favourites").getByRole("button", { name: `Open ${names[0]}` })).toBeVisible();
    await page.reload();
    await expect(page.getByTestId("favourites").getByRole("button", { name: `Open ${names[0]}` })).toBeVisible();

    // organise: create a section and file the other app into it
    await page.getByTestId("organise-toggle").click();
    await page.getByLabel("New section name").fill(`Work ${tag}`);
    await page.getByTestId("add-section").click();
    await expect(page.getByRole("heading", { name: `Work ${tag}` })).toBeVisible();
    await page.getByLabel(`Section for ${names[1]}`).selectOption({ label: `Work ${tag}` });
    const sec = page.locator("[data-testid^=section-]").filter({ hasText: `Work ${tag}` });
    await expect(sec.getByRole("button", { name: `Open ${names[1]}` })).toBeVisible();
    sectionId = Number((await sec.getAttribute("data-testid"))!.replace("section-", ""));
    await page.getByTestId("organise-toggle").click();

    // launching records "Recently used"
    const [popup] = await Promise.all([context.waitForEvent("page"), page.getByRole("button", { name: `Open ${names[1]}` }).click()]);
    await popup.close();
    await page.reload();
    await expect(page.getByTestId("recent-apps").getByRole("button", { name: `Recent: ${names[1]}` })).toBeVisible();

    // search hides the recents row and filters across groups
    await page.getByLabel("Search my apps").fill("Amy");
    await expect(page.getByRole("button", { name: `Open ${names[0]}` })).toHaveCount(0);
    await expect(page.getByRole("button", { name: `Open ${names[1]}` })).toBeVisible();
    await expect(page.getByTestId("recent-apps")).toHaveCount(0);

    // own recent sign-ins are listed
    await expect(page.getByTestId("recent-activity")).toContainText("Signed in");
  } finally {
    if (sectionId) await api(page, "DELETE", `/me/dashboard/sections/${sectionId}`);
    for (const id of ids) await api(page, "DELETE", `/admin/applications/${id}`);
  }
});
