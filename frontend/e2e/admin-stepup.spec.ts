import { expect, test } from "@playwright/test";
import { login } from "./helpers";
import { totp } from "./totp";

// IFORA-33: a sensitive admin change asks for a fresh authenticator code. Needs a stack with ADMIN_MFA_REQUIRED=true and a short
// proof window (ADMIN_STEPUP_MINUTES=1), and a THROWAWAY super admin that has already enrolled an authenticator:
//   E2E_STEPUP_EMAIL, E2E_STEPUP_PASSWORD, E2E_STEPUP_TOTP_SECRET (base32)
const email = process.env.E2E_STEPUP_EMAIL ?? "";
const password = process.env.E2E_STEPUP_PASSWORD ?? "";
const secret = process.env.E2E_STEPUP_TOTP_SECRET ?? "";
test.skip(!email || !password || !secret, "set E2E_STEPUP_EMAIL / _PASSWORD / _TOTP_SECRET for a throwaway enrolled super admin");
test.setTimeout(240_000);

let lastStep = -1;
/** A fresh single-use code: wait for the next 30 s step if this one was already spent. */
async function freshCode(page: import("@playwright/test").Page) {
  let step = Math.floor(Date.now() / 30000);
  if (step <= lastStep) {
    await page.waitForTimeout((lastStep + 1) * 30000 - Date.now() + 500);
    step = lastStep + 1;
  }
  lastStep = step;
  return totp(secret);
}

test("a sensitive change asks for a code once the proof is old; a wrong code or cancel changes nothing", async ({ page }) => {
  await login(page, email, password);
  await page.locator("#mfa-code").fill(await freshCode(page));
  await page.getByRole("button", { name: "Verify" }).click();
  await expect(page).toHaveURL(/\/admin\/dashboard/);

  const tag = Date.now();
  const name = `Stepup ${tag}`;
  await page.goto("/admin/network-zones");
  await page.waitForTimeout(65_000); // the signing-in proof (1 minute window) is now old

  // 1. the dialog appears; a wrong code is refused inline
  await page.getByTestId("zone-new").click();
  await page.locator("#z-name").fill(name);
  await page.locator("#z-cidrs").fill("10.9.0.0/16");
  await page.getByTestId("zone-save").click();
  const dialog = page.getByTestId("stepup-dialog");
  await expect(dialog).toBeVisible();
  await expect(dialog).toHaveAttribute("aria-modal", "true");
  await expect(page.locator("#stepup-code")).toBeFocused();
  await page.locator("#stepup-code").fill("000000");
  await page.getByTestId("stepup-confirm").click();
  await expect(dialog.getByRole("alert")).toContainText(/invalid|expired/i);

  // 2. cancelling leaves everything as it was
  await dialog.getByRole("button", { name: "Cancel" }).click();
  await expect(dialog).toHaveCount(0);
  await expect(page.getByTestId("zones-table")).not.toContainText(name);

  // 3. a right code lets the same change through, with no second prompt for the next one
  await page.getByTestId("zone-save").click();
  await expect(dialog).toBeVisible();
  await page.locator("#stepup-code").fill(await freshCode(page));
  await page.getByTestId("stepup-confirm").click();
  await expect(dialog).toHaveCount(0);
  await expect(page.getByTestId("zones-table")).toContainText(name);

  // clean up (inside the window: no prompt)
  page.once("dialog", (d) => d.accept());
  await page.getByRole("button", { name: `Delete ${name}` }).click();
  await expect(page.getByTestId("zones-table")).not.toContainText(name);
});
