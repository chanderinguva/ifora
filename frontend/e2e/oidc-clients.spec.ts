import { expect, test } from "@playwright/test";
import { loginAsAdmin } from "./helpers";

const name = `E2E app ${Date.now()}`;

test("register a confidential OIDC client, see the secret once, rotate it, and delete it", async ({ page }) => {
  page.on("dialog", (d) => d.accept());
  await loginAsAdmin(page);
  await page.goto("/admin/oidc-clients");
  await page.getByRole("button", { name: "Add application" }).click();
  await page.locator("#c-name").fill(name);
  await page.getByLabel(/Confidential/).check();
  await page.locator("#c-redirects").fill("http://evil.example.com/cb");
  await page.getByRole("button", { name: "Create application" }).click();
  await expect(page.getByRole("status")).toContainText(/https/); // insecure redirect URI refused

  await page.locator("#c-redirects").fill("https://app.example.com/callback");
  await page.getByRole("button", { name: "Create application" }).click();
  const secret = page.getByTestId("client-secret");
  await expect(secret).toContainText("idf_cs_");
  await page.getByRole("button", { name: "I have stored it" }).click();
  await expect(page.getByTestId("client-secret")).toHaveCount(0);

  const card = page.getByTestId("client-list").locator("> div", { hasText: name });
  await expect(card).toContainText("confidential");
  await expect(card).not.toContainText("idf_cs_"); // the secret is not shown again
  await card.getByRole("button", { name: "Add secret (rotation)" }).click();
  await expect(page.getByTestId("client-secret")).toContainText("idf_cs_");
  await page.getByRole("button", { name: "I have stored it" }).click();
  await expect(card.getByText("active", { exact: true })).toHaveCount(3); // client + 2 secrets

  await card.getByRole("button", { name: "Delete" }).last().click();
  await expect(page.getByTestId("client-list")).not.toContainText(name);
});
