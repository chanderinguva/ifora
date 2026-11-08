import { expect, test } from "@playwright/test";
import { loginAsAdmin } from "./helpers";

const name = `E2E scim ${Date.now()}`;

// NOT RUN by the author of this change (no access to the dev stack); to be run by the lead.
test("create a SCIM token, see it once, use the base URL, revoke it", async ({ page }) => {
  page.on("dialog", (d) => d.accept());
  await loginAsAdmin(page);
  await page.goto("/admin/provisioning");
  await expect(page.getByTestId("scim-base-url")).toContainText("/scim/v2");

  await page.getByRole("button", { name: "Create token" }).first().click();
  await page.locator("#t-name").fill(name);
  await page.getByRole("button", { name: "Create token" }).last().click();
  const reveal = page.getByTestId("scim-token");
  await expect(reveal).toContainText("idf_scim_");
  await page.getByRole("button", { name: "I have stored it" }).click();
  await expect(page.getByTestId("scim-token")).toHaveCount(0);

  const row = page.getByTestId("scim-token-list").locator("> div", { hasText: name });
  await expect(row).toContainText("active");
  await expect(row).not.toContainText(/idf_scim_[A-Za-z0-9_-]{20,}/); // only the short prefix is listed
  await row.getByRole("button", { name: "Revoke" }).click();
  await expect(row).toContainText("revoked");
});

test("Inbound SCIM is reachable from the navigation", async ({ page }) => {
  await loginAsAdmin(page);
  await page.getByRole("link", { name: "Inbound SCIM" }).click();
  await expect(page).toHaveURL(/\/admin\/provisioning/);
});
