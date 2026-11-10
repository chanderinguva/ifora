import { expect, test } from "@playwright/test";
import { loginAsAdmin } from "./helpers";

test.use({ viewport: { width: 1280, height: 1100 } });
const stamp = Date.now();
const connName = `E2E GitHub ${stamp}`;

test("connect a pre-built connector, see it listed, test it, edit without re-entering the secret, delete it", async ({ page }) => {
  await loginAsAdmin(page);
  page.on("dialog", (d) => d.accept());
  await page.goto("/admin/recipes/connections");

  // the catalog offers the five phase-1 connectors
  const catalog = page.getByTestId("connector-catalog");
  for (const name of ["GitHub", "Jira Cloud", "Slack", "PagerDuty", "Microsoft Entra ID"]) await expect(catalog).toContainText(name);

  // the form is generated from the connector's fields and tells you what is missing
  await page.getByRole("button", { name: "Connect GitHub" }).click();
  const form = page.getByTestId("connector-connection-editor");
  await expect(form).toContainText("Connect GitHub");
  await expect(page.getByTestId("connector-problem")).toBeVisible();
  await expect(form.getByRole("button", { name: "Save connection" })).toBeDisabled();

  // a value the definition forbids is refused by the server
  await form.getByLabel("Name", { exact: true }).fill(connName);
  await form.getByLabel("Organisation").fill("not/valid");
  await form.getByLabel("Personal access token or app token").fill("ghp_e2e_fake_token_value");
  await form.getByRole("button", { name: "Save connection" }).click();
  await expect(page.getByRole("status").filter({ hasText: "invalid format" })).toBeVisible();

  await form.getByLabel("Organisation").fill("acme-e2e");
  await form.getByRole("button", { name: "Save connection" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Connection saved" })).toBeVisible();

  // listed, secret hidden
  const row = page.getByTestId("connections-table").locator("tr", { hasText: connName });
  await expect(row).toContainText("GitHub");
  await expect(row).toContainText("api.github.com");
  await expect(row).toContainText("stored, hidden");
  await expect(page.locator("body")).not.toContainText("ghp_e2e_fake_token_value");

  // the test button answers with a message either way (the fake token is refused, or the sandbox has no egress)
  await row.getByRole("button", { name: "Test" }).click();
  await expect(page.getByRole("status").filter({ hasText: connName })).toBeVisible();

  // edit: settings are filled in, the secret is empty and optional
  await row.getByRole("button", { name: "Edit" }).click();
  await expect(form.getByLabel("Organisation")).toHaveValue("acme-e2e");
  await expect(form.getByLabel(/Personal access token/)).toHaveValue("");
  await form.getByLabel("Organisation").fill("acme-e2e-2");
  await form.getByRole("button", { name: "Save connection" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Connection saved" })).toBeVisible();

  await row.getByRole("button", { name: "Delete" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Connection deleted" })).toBeVisible();
  await expect(page.getByTestId("connections-table")).not.toContainText(connName);
});
