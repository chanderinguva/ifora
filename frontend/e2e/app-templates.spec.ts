import { expect, test } from "@playwright/test";
import { loginAsAdmin } from "./helpers";

test("create an application from the generic OIDC template: disabled, checklist shown, secret shown once", async ({ page }) => {
  page.on("dialog", (d) => d.accept());
  const name = `E2E template ${Date.now()}`;
  await loginAsAdmin(page);
  await page.goto("/admin/applications/new");
  await page.getByTestId("wizard-view-templates").click();
  await page.getByTestId("tpl-oidc-web").click();

  // Create stays disabled until the required redirect URI is filled in, and a wildcard is refused by the server
  await page.locator("#t-name").fill(name);
  await expect(page.getByTestId("template-create")).toBeDisabled();
  await page.locator("#t-redirect_uri").fill("https://*.example.com/cb");
  await page.getByTestId("template-create").click();
  await expect(page.getByRole("status")).toBeVisible();

  await page.locator("#t-redirect_uri").fill("https://app.example.com/cb");
  await page.getByTestId("template-create").click();
  const done = page.getByTestId("template-created");
  await expect(done).toBeVisible();
  await expect(done).toContainText("disabled");
  await expect(page.getByTestId("new-secret")).toBeVisible();
  await expect(page.getByTestId("template-checklist").locator("li")).not.toHaveCount(0);

  await done.getByRole("button", { name: "Continue to the application" }).click();
  await expect(page).toHaveURL(/\/admin\/applications\/\d+$/);
  await expect(page.getByRole("heading", { name })).toBeVisible();
});

test("a provisioning template asks only for what the vendor does not fix", async ({ page }) => {
  await loginAsAdmin(page);
  await page.goto("/admin/applications/new");
  await page.getByTestId("wizard-view-templates").click();
  await page.getByTestId("tpl-slack").click();
  await expect(page.locator("#t-secret")).toHaveAttribute("type", "password");
  await expect(page.locator("#t-base_url")).toHaveCount(0); // Slack's SCIM endpoint is fixed by the template
  await page.getByRole("button", { name: "Back to templates" }).click();
  await page.getByTestId("tpl-github").click();
  await expect(page.locator("#t-base_url")).toBeVisible();
});
