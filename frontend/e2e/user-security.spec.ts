import { expect, test } from "@playwright/test";
import { loginAsAdmin } from "./helpers";

// IFORA-43: the account owner sees where they are signed in, signs another device out (password required),
// and sees that in their own recent activity.
test("sign out another device from account settings", async ({ page, browser }) => {
  await loginAsAdmin(page);

  // a second browser, as a second device
  const other = await browser.newContext({ userAgent: "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0" });
  const otherPage = await other.newPage();
  try {
    await loginAsAdmin(otherPage);

    await page.goto("/settings");
    const rows = page.getByTestId("session-row");
    await expect(rows.first()).toBeVisible();
    const count = await rows.count();
    expect(count).toBeGreaterThanOrEqual(2);
    await expect(page.getByTestId("sessions")).toContainText("this device");
    await expect(page.getByTestId("sessions")).toContainText("Firefox");
    // no database ids leak into the page
    expect(await page.getByTestId("sessions").innerHTML()).not.toMatch(/"id"|data-id/);

    // the wrong password changes nothing
    await page.getByRole("button", { name: /^Sign out Firefox/ }).first().click();
    await page.getByLabel(/Confirm your password/).fill("definitely-not-the-password");
    await page.getByTestId("session-reauth").getByRole("button", { name: "Sign out", exact: true }).click();
    await expect(page.getByTestId("sessions-msg")).toContainText(/password/i);
    await expect(rows).toHaveCount(count);

    // the right one signs that device out
    const pw = process.env.ADMIN_PASSWORD ?? "";
    await page.getByLabel(/Confirm your password/).fill(pw);
    await page.getByTestId("session-reauth").getByRole("button", { name: "Sign out", exact: true }).click();
    await expect(page.getByTestId("sessions-msg")).toContainText("signed out");
    await expect(rows).toHaveCount(count - 1);

    // the other device really lost its session
    await otherPage.goto("/settings");
    await expect(otherPage).toHaveURL(/\/login/);

    // and it is in my own recent activity
    await expect(page.getByTestId("activity")).toContainText("Signed out another session");
  } finally {
    await other.close();
  }
});

test("sign out all other sessions asks for the password and leaves this one", async ({ page, browser }) => {
  await loginAsAdmin(page);
  const other = await browser.newContext();
  try {
    await loginAsAdmin(await other.newPage());
    await page.goto("/settings");
    await page.getByRole("button", { name: "Sign out all other sessions" }).click();
    await page.getByLabel(/Confirm your password/).fill(process.env.ADMIN_PASSWORD ?? "");
    await page.getByTestId("session-reauth").getByRole("button", { name: "Sign out", exact: true }).click();
    await expect(page.getByTestId("session-row")).toHaveCount(1);
    await expect(page.getByRole("button", { name: "Sign out all other sessions" })).toHaveCount(0);
    await page.reload();
    await expect(page.getByTestId("sessions")).toContainText("this device"); // still signed in
  } finally {
    await other.close();
  }
});
