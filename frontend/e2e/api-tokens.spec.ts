import { expect, request, test } from "@playwright/test";
import { ADMIN_PASSWORD, loginAsAdmin } from "./helpers";

const API = "http://localhost:8000/api/v1";

test("create an API token, use it as a bearer on the admin API, then revoke it", async ({ page }) => {
  page.on("dialog", (d) => d.accept());
  await loginAsAdmin(page);
  await page.goto("/admin/administrators");
  await expect(page.getByTestId("admins-table")).toBeVisible();
  await expect(page.getByTestId("admins-table")).toContainText("super administrator");

  await page.getByTestId("tab-tokens").click();
  await page.getByTestId("token-new").click();
  await page.locator("#t-name").fill(`e2e-${Date.now()}`);
  await page.locator("#t-pw").fill(ADMIN_PASSWORD);
  await page.locator("#t-cidrs").fill("");
  await page.locator("input[type=checkbox]").first().check(); // read-only
  await page.getByTestId("token-create").click();
  const raw = (await page.getByTestId("token-value").innerText()).trim();
  expect(raw).toMatch(/^idf_api_/);

  // a bare client (no cookies): read works, write is refused, self-service is off limits
  const bare = await request.newContext();
  expect((await bare.get(`${API}/admin/users`, { headers: { Authorization: `Bearer ${raw}` } })).status()).toBe(200);
  expect((await bare.post(`${API}/admin/groups`, { headers: { Authorization: `Bearer ${raw}` }, data: { name: "nope" } })).status()).toBe(403);
  expect((await bare.get(`${API}/me`, { headers: { Authorization: `Bearer ${raw}` } })).status()).toBe(403);
  await expect(page.getByTestId("tokens-table")).toContainText("read-only");

  // revoke from the UI; the token stops working at once
  await page.getByRole("button", { name: /^Revoke / }).first().click();
  await expect(page.getByText("Token revoked")).toBeVisible();
  expect((await bare.get(`${API}/admin/users`, { headers: { Authorization: `Bearer ${raw}` } })).status()).toBe(401);
  await bare.dispose();
});
