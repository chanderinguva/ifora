import { expect, test } from "@playwright/test";
import { readFileSync } from "fs";
import { loginAsAdmin } from "./helpers";

test("developers page: live API reference, samples, Postman collection, SDK and MCP guides", async ({ page }) => {
  await loginAsAdmin(page);
  await page.getByRole("link", { name: "API & SDKs" }).click();
  await expect(page).toHaveURL(/\/admin\/developers/);
  await expect(page.getByRole("heading", { name: "Developers" })).toBeVisible();

  // getting started shows the SCIM response shapes
  await expect(page.getByLabel("List")).toContainText("urn:ietf:params:scim:api:messages:2.0:ListResponse");
  await expect(page.getByLabel("Error")).toContainText("urn:ietf:params:scim:api:messages:2.0:Error");
  await expect(page.getByLabel("Resource", { exact: true })).toContainText('"meta"');

  // reference: every operation from the live OpenAPI document, searchable
  await page.getByRole("tab", { name: "API reference" }).click();
  await expect(page.getByTestId("api-op").first()).toBeVisible();
  const total = await page.getByTestId("api-op").count();
  expect(total).toBeGreaterThan(200);
  await page.getByLabel("Search endpoints").fill("provisioning-apps");
  const narrowed = await page.getByTestId("api-op").count();
  expect(narrowed).toBeGreaterThan(0);
  expect(narrowed).toBeLessThan(total);

  // an operation opens with samples that use the right auth for its path
  await page.getByTestId("api-op").filter({ hasText: "POST" }).first().locator("button").first().click();
  await expect(page.getByLabel("curl example")).toContainText("Authorization: Bearer $IFORA_API_TOKEN");
  await page.getByRole("tab", { name: "Python" }).click();
  await expect(page.getByLabel("python example")).toContainText("requests.post(");

  // Postman collection is generated from the same spec: one request per operation
  await page.getByRole("tab", { name: "Postman & OpenAPI" }).click();
  const [download] = await Promise.all([page.waitForEvent("download"), page.getByTestId("download-postman").click()]);
  const col = JSON.parse(readFileSync((await download.path())!, "utf8"));
  expect(col.info.schema).toContain("v2.1.0");
  expect(col.variable.map((v: { key: string }) => v.key)).toEqual(expect.arrayContaining(["baseUrl", "apiToken"]));
  const requests = col.item.reduce((n: number, f: { item: unknown[] }) => n + f.item.length, 0);
  expect(requests).toBe(total);

  await page.getByRole("tab", { name: "SDKs" }).click();
  await expect(page.getByText("openapi-generator-cli generate").first()).toBeVisible();
  await expect(page.getByLabel("Python SDK example")).toContainText("from ifora import Client");
  await page.getByRole("tab", { name: "MCP" }).click();
  await expect(page.getByLabel("Claude Code command")).toContainText("openapi-mcp-server");
});
