import { expect, test } from "@playwright/test";
import { loginAsAdmin } from "./helpers";

const name = `E2E service ${Date.now()}`;
const API = "https://api.example.com";

test("a service client is registered in the UI, gets a client-credentials token, and the token introspects", async ({ page, request }) => {
  page.on("dialog", (d) => d.accept());
  await loginAsAdmin(page);
  await page.goto("/admin/oidc-clients");
  await page.getByRole("button", { name: "Add application" }).click();
  await page.locator("#c-name").fill(name);
  await page.getByLabel(/Service/).check();
  await expect(page.locator("#c-redirects")).toHaveCount(0); // no redirect URIs for a machine client
  await page.locator("#c-sscopes").fill("invoices:read\ninvoices:write");
  await page.locator("#c-audiences").fill(API);
  await page.getByRole("button", { name: "Create application" }).click();
  const secret = ((await page.getByTestId("client-secret").innerText()).match(/idf_cs_\S+/) ?? [])[0]!;
  expect(secret).toBeTruthy();
  await page.getByRole("button", { name: "I have stored it" }).click();
  const card = page.getByTestId("client-list").locator("> div", { hasText: name });
  await expect(card).toContainText("service");
  await expect(card).toContainText(API);
  const clientId = (await card.locator("code.select-all").first().innerText()).trim();

  const auth = "Basic " + Buffer.from(`${clientId}:${secret}`).toString("base64");
  const tok = await request.post("http://localhost:8000/oauth/token", { headers: { Authorization: auth }, form: { grant_type: "client_credentials", scope: "invoices:read" } });
  expect(tok.ok()).toBeTruthy();
  const body = await tok.json();
  expect(body.scope).toBe("invoices:read");
  expect(body.id_token).toBeUndefined();
  const intro = await request.post("http://localhost:8000/oauth/introspect", { headers: { Authorization: auth }, form: { token: body.access_token } });
  expect(await intro.json()).toMatchObject({ active: true, client_id: clientId, aud: API, scope: "invoices:read" });

  await card.getByRole("button", { name: "Delete" }).last().click();
  await expect(page.getByTestId("client-list")).not.toContainText(name);
});
