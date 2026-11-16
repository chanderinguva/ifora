import { expect, test } from "@playwright/test";
import { loginAsAdmin } from "./helpers";

// IFORA-42: the first-run checklist ticks itself from real objects, items can be skipped and restored, and the task entry
// points work from the dashboard and the command palette. Leaves no data behind.
test("task entry points: dashboard cards and the command palette", async ({ page }) => {
  await loginAsAdmin(page);
  await expect(page.getByTestId("quick-tasks")).toBeVisible();
  await page.getByTestId("quick-add-app").click();
  await expect(page).toHaveURL(/\/admin\/applications\/new/);

  await page.goto("/admin/dashboard");
  await page.getByTestId("quick-onboard-user").click();
  await expect(page).toHaveURL(/\/admin\/users\?new=1/);
  await expect(page.getByRole("button", { name: "Create user" })).toBeVisible(); // the form is already open

  await page.goto("/admin/dashboard");
  await expect(page.getByTestId("open-search")).toBeVisible(); // hydrated
  await page.keyboard.press("Control+k");
  await page.getByRole("combobox", { name: "Search" }).fill("failed sign-in");
  await expect(page.getByRole("option", { name: /Investigate a login/ })).toBeVisible();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/admin\/audit\?action=LOGIN_FAILURE/);

  await page.goto("/admin/dashboard");
  await expect(page.getByTestId("open-search")).toBeVisible(); // hydrated
  await page.keyboard.press("Control+k");
  await page.getByRole("combobox", { name: "Search" }).fill("simulate");
  await expect(page.getByRole("option", { name: /Test a sign-on policy/ })).toBeVisible();
});

test("checklist: skip, show again, and ticking from real data", async ({ page }) => {
  await loginAsAdmin(page);
  const card = page.getByTestId("setup-checklist");
  if (!(await card.isVisible())) test.skip(true, "this stack has already completed every setup item");

  const first = card.locator("[data-testid^=setup-]:not([data-testid=setup-progress])").first();
  const id = (await first.getAttribute("data-testid"))!.replace("setup-", "");
  const title = (await first.locator("span.font-medium").innerText()).trim();
  await first.getByRole("button", { name: `Skip ${title}` }).click();
  await expect(page.getByTestId(`setup-${id}`)).toHaveCount(0);
  await page.reload(); // the dismissal is stored, not remembered by the page
  await expect(page.getByTestId(`setup-${id}`)).toHaveCount(0);
  await page.getByRole("button", { name: /^Show \d+ skipped$/ }).click();
  await page.getByRole("button", { name: `Show ${title}` }).click(); // "Show again" restores it
  await expect(page.getByTestId(`setup-${id}`)).toBeVisible();

  // a real object ticks its item without anyone pressing anything
  const tag = Date.now();
  const before = await page.getByTestId("setup-progress").innerText();
  const made = await page.evaluate(async ([base, name]) => {
    const me = await (await fetch(`${base}/me`, { credentials: "include" })).json();
    const r = await fetch(`${base}/admin/network-zones`, { method: "POST", credentials: "include", headers: { "Content-Type": "application/json", "X-CSRF-Token": me.csrf_token }, body: JSON.stringify({ name, cidrs: ["10.77.0.0/16"] }) });
    return { status: r.status, id: (await r.json()).id };
  }, [`${process.env.E2E_API ?? "http://localhost:8000/api/v1"}`, `FirstRun ${tag}`] as const);
  try {
    expect(made.status).toBeLessThan(300);
    await page.reload();
    if (!before.startsWith("5 ")) await expect(page.getByTestId("setup-progress")).not.toHaveText(before);
  } finally {
    await page.evaluate(async ([base, zid]) => {
      const me = await (await fetch(`${base}/me`, { credentials: "include" })).json();
      await fetch(`${base}/admin/network-zones/${zid}`, { method: "DELETE", credentials: "include", headers: { "X-CSRF-Token": me.csrf_token } });
    }, [`${process.env.E2E_API ?? "http://localhost:8000/api/v1"}`, made.id] as const);
  }
});
