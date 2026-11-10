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

test("the editor offers the connector action step and its outputs become datapills", async ({ page }) => {
  const name = `E2E GitHub editor ${stamp}`;
  const recipeName = `E2E connector step ${stamp}`;
  await loginAsAdmin(page);
  page.on("dialog", (d) => d.accept());

  await page.goto("/admin/recipes/connections");
  await page.getByRole("button", { name: "Connect GitHub" }).click();
  const form = page.getByTestId("connector-connection-editor");
  await form.getByLabel("Name", { exact: true }).fill(name);
  await form.getByLabel("Organisation").fill("acme-e2e");
  await form.getByLabel("Personal access token or app token").fill("ghp_e2e_fake_token_value");
  await form.getByRole("button", { name: "Save connection" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Connection saved" })).toBeVisible();

  await page.goto("/admin/recipes");
  await page.getByRole("button", { name: "New recipe" }).click();
  await page.locator("#rc-name").fill(recipeName);
  await page.getByRole("button", { name: "Create and open builder" }).click();
  await page.getByRole("button", { name: "Add a step", exact: true }).first().click();

  // the menu lists each connection's actions directly, grouped under the connection (the generic step is not offered while a connection exists)
  const menu = page.getByTestId("studio-menu");
  await expect(menu.getByTestId("studio-menu-group").filter({ hasText: name })).toBeVisible();
  await expect(menu.getByRole("menuitem", { name: "Run a connector action", exact: true })).toHaveCount(0);
  await menu.getByRole("menuitem", { name: `${name}: Get user`, exact: true }).click();

  // the step arrives with the connection and action already chosen
  const stepForm = page.getByTestId("connector-step-form");
  await expect(stepForm.getByLabel("Connection")).toContainText(name);
  await expect(stepForm.getByLabel("Action")).toHaveValue("get_user");
  await stepForm.getByLabel("GitHub username", { exact: true }).fill("octocat");
  await expect(stepForm).toContainText("Later steps can use");
  await expect(stepForm).toContainText("login");
  await expect(stepForm).toContainText("Retried automatically");

  // a later step can pick the action's outputs
  await page.getByRole("button", { name: "Add a step at position 2", exact: true }).first().click();   // right after the connector step, in the main lane
  await page.getByRole("menuitem", { name: "Write to the job log", exact: true }).click();
  await page.getByTestId("pill-tray").getByLabel("Search data").fill("login");
  await expect(page.locator('[data-testid="pill-chip"][data-path$="output.login"]')).toBeVisible();

  await page.goto("/admin/recipes");
  await page.getByTestId("recipes-table").locator("tr", { hasText: recipeName }).getByRole("button", { name: "Delete" }).click();
  await expect(page.getByTestId("recipes-table")).not.toContainText(recipeName);
  await page.goto("/admin/recipes/connections");
  await page.getByTestId("connections-table").locator("tr", { hasText: name }).getByRole("button", { name: "Delete" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Connection deleted" })).toBeVisible();
});
