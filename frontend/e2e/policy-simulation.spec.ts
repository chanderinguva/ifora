import { expect, test } from "@playwright/test";
import { ADMIN_EMAIL, loginAsAdmin } from "./helpers";

// IFORA-33: "Test this policy" on an application's Sign On tab. Needs only the normal admin sign-in.
test("policy simulation: judge a sign-in before saving, compare a draft, save nothing", async ({ page }) => {
  await loginAsAdmin(page);
  const tag = Date.now();
  const zoneName = `E2E Sim Office ${tag}`;

  await page.goto("/admin/network-zones");
  await page.getByTestId("zone-new").click();
  await page.locator("#z-name").fill(zoneName);
  await page.locator("#z-cidrs").fill("203.0.113.0/24");
  await page.getByTestId("zone-save").click();
  await expect(page.getByTestId("zones-table")).toContainText(zoneName);

  await page.goto("/admin/applications/new");
  await page.getByTestId("method-saml").click();
  await page.getByTestId("wizard-next").click();
  await page.locator("#a-name").fill(`E2E Sim ${tag}`);
  await page.locator("#a-acs").fill("https://sp.sim.example.com/acs");
  await page.locator("#a-ent").fill(`https://sp.sim.example.com/meta-${tag}`);
  await page.getByTestId("wizard-create").click();
  await expect(page).toHaveURL(/\/admin\/applications\/\d+$/);
  await page.getByTestId("tab-signon").click();

  const card = page.getByTestId("auth-policy");
  await card.getByLabel(zoneName).first().check(); // "Only allow these networks": an unsaved draft
  const sim = page.getByTestId("policy-simulator");

  // outside the allowed network: denied under the draft, allowed under the (empty) saved policy
  await sim.locator("#sim-email").fill(ADMIN_EMAIL);
  await sim.locator("#sim-ip").fill("198.51.100.7");
  await expect(sim.getByTestId("sim-draft")).toBeChecked();
  await sim.getByTestId("sim-run").click();
  const result = sim.getByTestId("sim-result");
  await expect(result).toBeVisible();
  await expect(result.locator("[data-decision=allow]")).toHaveCount(1); // saved policy
  await expect(result.locator("[data-decision=deny]")).toHaveCount(1); // with the changes
  await expect(result.getByTestId("sim-changed")).toContainText("would change the outcome");
  await expect(result).toContainText("approved network");

  // from inside the network the draft allows it
  await sim.locator("#sim-ip").fill("203.0.113.9");
  await sim.getByTestId("sim-run").click();
  await expect(result.getByTestId("sim-changed")).toContainText("would not change the outcome");

  // validation is shown, not swallowed
  await sim.locator("#sim-ip").fill("not-an-ip");
  await sim.getByTestId("sim-run").click();
  await expect(sim.getByRole("alert")).toContainText(/IPv4 or IPv6/);

  // nothing was saved by testing
  await page.reload();
  await page.getByTestId("tab-signon").click();
  await expect(page.getByTestId("auth-policy").getByLabel(zoneName).first()).not.toBeChecked();

  // clean up
  await page.goto("/admin/applications");
  await page.getByRole("link", { name: `E2E Sim ${tag}` }).click();
  page.once("dialog", (d) => d.accept());
  await page.getByRole("button", { name: "Delete" }).click();
  await expect(page).toHaveURL(/\/admin\/applications$/);
  await page.goto("/admin/network-zones");
  page.once("dialog", (d) => d.accept());
  await page.getByRole("button", { name: `Delete ${zoneName}` }).click();
  await expect(page.getByTestId("zones-table")).not.toContainText(zoneName);
});
