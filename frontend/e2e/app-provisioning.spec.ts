import { expect, test } from "@playwright/test";
import { loginAsAdmin } from "./helpers";

const name = `E2E app ${Date.now()}`;

// Needs a super admin (the e2e runner's throwaway account is one). The target host is public but unreachable on purpose:
// the UI must report the failed test and refuse to turn provisioning on.
test("add a SCIM application, assign a group, see the failed connection test, remove it", async ({ page }) => {
  page.on("dialog", (d) => d.accept());
  await loginAsAdmin(page);
  await page.getByRole("link", { name: "Provisioning apps" }).click();
  await expect(page).toHaveURL(/\/admin\/app-provisioning$/);

  await page.getByTestId("add-app").click();
  await page.locator("#a-name").fill(name);
  await page.locator("#a-url").fill("https://scim.invalid/scim/v2");
  await page.locator("#a-secret").fill("e2e-token-not-real");
  await page.getByRole("button", { name: "Create", exact: true }).click();
  await expect(page).toHaveURL(/\/admin\/app-provisioning\/\d+$/);
  await expect(page.getByRole("heading", { name })).toBeVisible();
  await expect(page.getByTestId("last-test")).toContainText("Not tested yet");
  await expect(page.getByTestId("enable-app")).toBeDisabled();

  await page.getByTestId("test-app").click();
  await expect(page.getByTestId("last-test")).toContainText("failed");   // unreachable host: reported, nothing sent
  await expect(page.getByTestId("enable-app")).toBeDisabled();

  // assign the first available group; it is listed and can be removed
  const groupSelect = page.getByLabel("Assign a group");
  const options = await groupSelect.locator("option").all();
  if (options.length > 1) {
    await groupSelect.selectOption({ index: 1 });
    await page.getByRole("button", { name: "Assign" }).last().click();
    await expect(page.getByTestId("assignments")).toBeVisible();
    await page.getByTestId("assignments").getByRole("button", { name: /^Remove / }).first().click();
  }

  // mapping rule validation comes from the server
  await page.getByRole("button", { name: "Add rule" }).click();
  await page.getByLabel("Target attribute").fill("userName");
  await page.getByLabel("Source").fill("email");
  await page.getByTestId("save-mapping").click();
  await expect(page.getByRole("status")).toContainText("set by IdentityForge");

  await page.getByRole("button", { name: "Delete" }).click();
  await expect(page).toHaveURL(/\/admin\/app-provisioning$/);
  await expect(page.getByText(name)).toHaveCount(0);
});
