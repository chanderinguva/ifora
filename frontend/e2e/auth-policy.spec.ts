import { expect, test } from "@playwright/test";
import { loginAsAdmin } from "./helpers";

test("network zones and a per-application authentication policy: create, attach, persist, clean up", async ({ page }) => {
  await loginAsAdmin(page);
  const tag = Date.now();
  const zoneName = `E2E Office ${tag}`;

  await page.goto("/admin/network-zones");
  await page.getByTestId("zone-new").click();
  await page.locator("#z-name").fill(zoneName);
  await page.locator("#z-cidrs").fill("not-an-ip");
  await page.getByTestId("zone-save").click();
  await expect(page.getByText(/not a valid IP address/)).toBeVisible(); // validated server-side, message shown
  await page.locator("#z-cidrs").fill("203.0.113.0/24\n2001:db8::/32");
  await page.getByTestId("zone-save").click();
  await expect(page.getByTestId("zones-table")).toContainText(zoneName);

  // a SAML app gets the policy card on its Sign On tab
  await page.goto("/admin/applications/new");
  await page.getByTestId("method-saml").click();
  await page.getByTestId("wizard-next").click();
  await page.locator("#a-name").fill(`E2E Policy ${tag}`);
  await page.locator("#a-acs").fill("https://sp.policy.example.com/acs");
  await page.locator("#a-ent").fill(`https://sp.policy.example.com/meta-${tag}`);
  await page.getByTestId("wizard-create").click();
  await expect(page).toHaveURL(/\/admin\/applications\/\d+$/);
  await page.getByTestId("tab-signon").click();
  const card = page.getByTestId("auth-policy");
  await card.getByTestId("policy-mfa").check();
  await card.locator("#policy-reauth").selectOption("30");
  await card.getByLabel(zoneName).first().check(); // "Only allow these networks"
  await card.getByTestId("policy-save").click();
  await expect(card.getByText("Policy saved")).toBeVisible();

  // persisted
  await page.reload();
  await page.getByTestId("tab-signon").click();
  await expect(page.getByTestId("policy-mfa")).toBeChecked();
  await expect(page.locator("#policy-reauth")).toHaveValue("30");

  // the zone is in use, so it cannot be deleted yet
  await page.goto("/admin/network-zones");
  page.once("dialog", (d) => d.accept());
  await page.getByRole("button", { name: `Delete ${zoneName}` }).click();
  await expect(page.getByText(/used by an application policy/)).toBeVisible();

  // clean up: delete the app (its policy goes with it), then the zone
  await page.goto("/admin/applications");
  await page.getByRole("link", { name: `E2E Policy ${tag}` }).click();
  page.once("dialog", (d) => d.accept());
  await page.getByRole("button", { name: "Delete" }).click();
  await expect(page).toHaveURL(/\/admin\/applications$/);
  await page.goto("/admin/network-zones");
  page.once("dialog", (d) => d.accept());
  await page.getByRole("button", { name: `Delete ${zoneName}` }).click();
  await expect(page.getByTestId("zones-table")).not.toContainText(zoneName);
});
