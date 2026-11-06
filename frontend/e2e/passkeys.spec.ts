import { expect, test } from "@playwright/test";
import { USER_PASSWORD, login, loginAsAdmin, logout } from "./helpers";

const run = Date.now().toString(36);
const email = `e2e-pk-${run}@example.com`;

test("passkeys: register two, sign in usernameless, require them, admin resets", async ({ page }) => {
  // Chrome virtual authenticator (resident key + user verification)
  const cdp = await page.context().newCDPSession(page);
  await cdp.send("WebAuthn.enable");
  const addDevice = async () =>
    (
      await cdp.send("WebAuthn.addVirtualAuthenticator", {
        options: {
          protocol: "ctap2",
          transport: "internal",
          hasResidentKey: true,
          hasUserVerification: true,
          isUserVerified: true,
          automaticPresenceSimulation: true,
        },
      })
    ).authenticatorId;
  let device = await addDevice();

  await loginAsAdmin(page);
  await page.goto("/admin/users");
  await page.getByRole("button", { name: "New user" }).click();
  await page.locator("#nu-first").fill("Pass");
  await page.locator("#nu-last").fill("Key");
  await page.locator("#nu-email").fill(email);
  await page.getByLabel("I will set a password").check();
  await page.locator("#nu-pw").fill(USER_PASSWORD);
  await page.getByRole("button", { name: "Create user" }).click();
  await page.getByLabel("Search users").fill(email);
  await expect(page.getByTestId("users-table")).toContainText(email);
  await logout(page);

  await login(page, email, USER_PASSWORD);
  await expect(page).toHaveURL(/\/dashboard$/);
  await page.goto("/settings");
  const card = page.getByTestId("passkey-card");

  for (const n of ["Laptop", "Phone"]) {
    // the server excludes credentials a device already holds, so a 2nd passkey needs a 2nd device
    if (n === "Phone") {
      await cdp.send("WebAuthn.removeVirtualAuthenticator", { authenticatorId: device });
      device = await addDevice();
    }
    await card.getByRole("button", { name: "Add a passkey" }).click();
    await page.locator("#pk-name").fill(n);
    await page.locator("#pk-pw").fill(USER_PASSWORD);
    await card.getByRole("button", { name: "Continue" }).click();
    await expect(card.getByTestId("passkey-list")).toContainText(n);
  }

  // require passkey
  await card.getByRole("button", { name: "Require a passkey to sign in" }).click();
  await page.locator("#pk-pw3").fill(USER_PASSWORD);
  await card.getByRole("button", { name: "Require passkey" }).click();
  await expect(card.getByRole("status")).toContainText("Passkey required");
  await logout(page);

  // password is refused, passkey works
  await login(page, email, USER_PASSWORD);
  await expect(page.getByText("requires signing in with a passkey")).toBeVisible();
  await page.getByRole("button", { name: "Sign in with a passkey" }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
  await logout(page);

  // admin resets sign-in factors
  await loginAsAdmin(page);
  await page.goto("/admin/users");
  await page.getByLabel("Search users").fill(email);
  await page.getByRole("link", { name: "Pass Key" }).click();
  page.once("dialog", (d) => d.accept());
  await page.getByRole("button", { name: /Reset MFA/ }).click();
  await expect(page.getByText("passkey required")).toHaveCount(0);
  await logout(page);
  await login(page, email, USER_PASSWORD);
  await expect(page).toHaveURL(/\/dashboard$/);
  await logout(page);

  // cleanup
  await loginAsAdmin(page);
  await page.goto("/admin/users");
  await page.getByLabel("Search users").fill(email);
  await page.getByRole("link", { name: "Pass Key" }).click();
  page.once("dialog", (d) => d.accept());
  await page.getByRole("button", { name: "Delete user" }).click();
  await expect(page).toHaveURL(/\/admin\/users$/);
});
