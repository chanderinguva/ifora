import { expect, test } from "@playwright/test";
import { deflateRawSync } from "zlib";
import { loginAsAdmin } from "./helpers";

const API = process.env.E2E_API_URL ?? "http://localhost:8000";
const ACS = "https://sp.e2e.example.com/acs";
const SP = `https://sp.e2e.example.com/meta-${Date.now()}`;

// The ACS is a public https URL that must never be contacted: the browser's POST is intercepted and inspected.
test("SAML application: configure in the UI, then IdP- and SP-initiated sign-in post a signed response to the ACS", async ({ page }) => {
  page.on("dialog", (d) => d.accept());
  const posts: { body: string }[] = [];
  await page.route(ACS, async (route) => {
    posts.push({ body: route.request().postData() ?? "" });
    await route.fulfill({ status: 200, contentType: "text/html", body: "<html><body>acs reached</body></html>" });
  });

  await loginAsAdmin(page);
  const name = `E2E SAML ${Date.now()}`;
  await page.goto("/admin/applications");
  await page.getByRole("button", { name: /Create App Integration/ }).click();
  await page.getByTestId("method-saml").click();
  await page.getByTestId("wizard-next").click();
  await page.locator("#a-name").fill(name);
  await page.locator("#a-acs").fill(ACS);
  await page.locator("#a-ent").fill(SP);
  await page.getByTestId("wizard-create").click();
  await expect(page).toHaveURL(/\/admin\/applications\/(\d+)$/);
  const appId = page.url().split("/").pop()!;
  await expect(page.getByTestId("saml-idp-info")).toContainText("/saml/metadata");

  await page.locator("#s-ent").fill(SP);
  await page.locator("#s-acs").fill(ACS);
  await page.getByRole("button", { name: "Save SAML settings" }).click();
  await expect(page.getByText("SAML settings saved")).toBeVisible();
  await expect(page.getByTestId("saml-idp-info")).toContainText("SHA-256");

  // JIT mapping: an expression attribute, then preview it for a user
  await page.getByRole("button", { name: "Add attribute" }).click();
  await page.getByLabel("Attribute name 4").fill("shout");
  await page.getByLabel("Attribute source 4").selectOption("expr");
  await page.getByLabel("Expression 4").fill("String.toUpperCase(user.firstName)");
  const [saved] = await Promise.all([
    page.waitForResponse((r) => r.url().includes("/saml") && r.request().method() === "PUT"),
    page.getByRole("button", { name: "Save SAML settings" }).click(),
  ]);
  expect(saved.status()).toBe(200);
  await page.getByLabel("Preview as user").selectOption({ index: 1 });
  await page.getByRole("button", { name: "Preview", exact: true }).click();
  await expect(page.getByTestId("saml-preview-result")).toContainText("shout");

  // let any signed-in user in (the throwaway admin is not assigned)
  await page.getByLabel(/Only assigned users may sign in/).uncheck();
  await page.getByRole("button", { name: "Save", exact: true }).first().click();
  await expect(page.getByText("Saved", { exact: true })).toBeVisible();

  // IdP-initiated
  await page.goto(`/saml/continue?app=${appId}`);
  await expect.poll(() => posts.length).toBe(1);
  const form = new URLSearchParams(posts[0].body);
  const xml = Buffer.from(form.get("SAMLResponse")!, "base64").toString();
  expect(xml).toContain("<ds:Signature");
  expect(xml).toContain(`Destination="${ACS}"`);
  expect(xml).not.toContain("InResponseTo");

  // SP-initiated, with RelayState
  const now = new Date().toISOString().replace(/\.\d+Z$/, "Z");
  const req = `<samlp:AuthnRequest xmlns:samlp="urn:oasis:names:tc:SAML:2.0:protocol" xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion" ID="_e2e1" Version="2.0" IssueInstant="${now}"><saml:Issuer>${SP}</saml:Issuer></samlp:AuthnRequest>`;
  const q = new URLSearchParams({ SAMLRequest: deflateRawSync(Buffer.from(req)).toString("base64"), RelayState: "relay-123" });
  await page.goto(`${API}/saml/sso?${q}`);
  await expect.poll(() => posts.length).toBe(2);
  const f2 = new URLSearchParams(posts[1].body);
  expect(f2.get("RelayState")).toBe("relay-123");
  expect(Buffer.from(f2.get("SAMLResponse")!, "base64").toString()).toContain('InResponseTo="_e2e1"');

  // a request from an unknown SP is refused with a readable message and nothing is posted anywhere
  const bad = req.replace(SP, "https://nobody.example.com/meta");
  await page.goto(`${API}/saml/sso?${new URLSearchParams({ SAMLRequest: deflateRawSync(Buffer.from(bad)).toString("base64") })}`);
  await expect(page.getByTestId("saml-error")).toContainText("Unknown service provider");
  expect(posts.length).toBe(2);

  await page.goto(`/admin/applications/${appId}`);
  await page.getByRole("button", { name: "Delete" }).click();
  await expect(page).toHaveURL(/\/admin\/applications$/);
});
