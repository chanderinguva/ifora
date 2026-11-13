import { expect, test } from "@playwright/test";
import { loginAsAdmin } from "./helpers";

test.use({ viewport: { width: 1280, height: 1000 } });

test("create a Slack bot connection inside a template without losing inputs", async ({ page }) => {
  await loginAsAdmin(page);
  const stamp = Date.now();
  const recipeName = "Inline alert " + stamp;
  const connectionName = "Inline Slack " + stamp;
  await page.goto("/admin/recipes");
  await page.getByRole("button", { name: "From template", exact: true }).click();
  await page.getByRole("button", { name: /Slack alert after repeated failed sign-ins/ }).click();
  await page.getByLabel("Recipe name", { exact: true }).fill(recipeName);
  await page.getByLabel("After this many failures").fill("3");
  await page.getByRole("button", { name: "Create connection", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Create connection" });
  await expect(dialog).toBeVisible();
  await dialog.getByLabel("Connection name", { exact: true }).fill(connectionName);
  const token = dialog.getByLabel(/Bot token/);
  await token.fill("xoxb-local-review-placeholder");
  await expect(token).toHaveAttribute("type", "password");
  await dialog.getByRole("button", { name: "Create connection", exact: true }).click();
  await expect(dialog).not.toBeVisible();
  await expect(page.getByLabel("Recipe name", { exact: true })).toHaveValue(recipeName);
  await expect(page.getByLabel("After this many failures")).toHaveValue("3");
  await expect(page.getByLabel("Slack connection", { exact: true })).toContainText(connectionName);
  await expect(page.getByLabel("Slack connection", { exact: true }).locator("option:checked")).toContainText(connectionName);
  await page.getByLabel("Slack channel or user ID").fill("C0123456789");
  await page.getByRole("button", { name: "Create draft from template" }).click();
  await expect(page.getByRole("heading", { name: recipeName, exact: true })).toBeVisible();
  await expect(page.getByTestId("studio")).toContainText("Post a message");
  await expect(page.getByRole("button", { name: "Publish", exact: true })).toHaveClass(/bg-primary/);
  await expect(page.getByRole("button", { name: "Validate draft", exact: true })).toBeVisible();
  const live = page.getByRole("region", { name: "Live Slack message test" });
  await page.getByLabel("Sample user", { exact: true }).selectOption({ index: 1 });
  await live.getByLabel("Test channel or user ID").fill("CTEST123");
  let sends = 0;
  await page.route("**/slack-test-preview", async (route) => {
    expect(route.request().postDataJSON().destination).toBe("CTEST123");
    await route.fulfill({ json: { preview_id: "a".repeat(64), destination: "CTEST123", text: "*Hello* test user :wave:" } });
  });
  await page.route("**/slack-test-send", async (route) => {
    sends += 1;
    expect(route.request().postDataJSON().confirmed).toBe(true);
    await route.fulfill({ json: { sent: true, destination: "CTEST123" } });
  });
  await live.getByRole("button", { name: "Preview test message", exact: true }).click();
  await expect(live).toContainText("*Hello* test user :wave:");
  const send = live.getByRole("button", { name: "Send test message", exact: true });
  await expect(send).toBeDisabled();
  expect(sends).toBe(0);
  await live.getByRole("checkbox").check();
  await send.click();
  await expect(page.getByTestId("builder-msg")).toContainText("Test message sent to CTEST123");
  expect(sends).toBe(1);
  await expect(send).not.toBeVisible();


  page.on("dialog", (d) => d.accept());
  await page.goto("/admin/recipes");
  await page.getByTestId("recipes-table").locator("tr", { hasText: recipeName }).getByRole("button", { name: "Delete", exact: true }).click();
  await page.goto("/admin/recipes/connections");
  await page.getByTestId("connections-table").locator("tr", { hasText: connectionName }).getByRole("button", { name: "Delete", exact: true }).click();
});

test("canceling an inline connection keeps an unsaved recipe draft", async ({ page }) => {
  await loginAsAdmin(page);
  const recipeName = "Preserve draft " + Date.now();
  page.on("dialog", (d) => d.accept());
  await page.goto("/admin/recipes");
  await page.getByRole("button", { name: "New recipe", exact: true }).click();
  await page.getByLabel("Recipe name", { exact: true }).fill(recipeName);
  await page.getByRole("button", { name: "Create and open builder" }).click();
  await expect(page.getByRole("heading", { name: recipeName, exact: true })).toBeVisible();
  await page.getByLabel("Recipe name", { exact: true }).fill(recipeName + " unsaved");
  await page.getByRole("button", { name: "Add a step", exact: true }).first().click();
  await page.getByRole("menuitem", { name: "Send an HTTP request", exact: true }).click();
  await page.getByRole("button", { name: "Create connection", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Create connection" });
  await dialog.getByLabel("Connection name", { exact: true }).fill("Canceled connection");
  await dialog.getByRole("button", { name: "Cancel", exact: true }).click();
  await expect(page.getByLabel("Recipe name", { exact: true })).toHaveValue(recipeName + " unsaved");
  await expect(page.getByText("Unsaved changes", { exact: true })).toBeVisible();
  await page.goto("/admin/recipes");
  await page.getByTestId("recipes-table").locator("tr", { hasText: recipeName }).getByRole("button", { name: "Delete", exact: true }).click();
});

test("generic HTTP connection stores arbitrary body credentials as masked fields", async ({ page }) => {
  await loginAsAdmin(page);
  const name = "Body credential " + Date.now();
  page.on("dialog", (d) => d.accept());
  await page.goto("/admin/recipes/connections");
  await page.getByRole("button", { name: "Connect API", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Create connection" });
  await dialog.getByLabel("Connection name", { exact: true }).fill(name);
  await dialog.getByLabel("Allowed API host", { exact: true }).fill("api.example.com");
  await dialog.getByLabel("Authentication", { exact: true }).selectOption("custom");
  await dialog.getByLabel("Send in", { exact: true }).selectOption("json");
  await dialog.getByLabel("Field name", { exact: true }).fill("opaque");
  await dialog.getByLabel("api key", { exact: true }).fill("LOCAL_BODY_SECRET_PLACEHOLDER");
  await expect(dialog.getByLabel("api key", { exact: true })).toHaveAttribute("type", "password");
  await dialog.getByRole("button", { name: "Create connection", exact: true }).click();
  const row = page.getByTestId("connections-table").locator("tr", { hasText: name });
  await expect(row).toContainText("HTTP / Custom API");
  await expect(page.locator("body")).not.toContainText("LOCAL_BODY_SECRET_PLACEHOLDER");
  await row.getByRole("button", { name: "Edit", exact: true }).click();
  const edit = page.getByRole("dialog", { name: "Edit connection" });
  await expect(edit.getByLabel(/api key/)).toHaveValue("");
  await edit.getByRole("button", { name: "Cancel", exact: true }).click();
  await row.getByRole("button", { name: "Delete", exact: true }).click();
});
