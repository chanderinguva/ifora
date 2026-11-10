import { expect, test } from "@playwright/test";
import { ADMIN_EMAIL, ADMIN_PASSWORD, loginAsAdmin, passSecondStep } from "./helpers";

// Needs the demo relying party (separate origin, :4000) started with DEMO_ALLOW_CONFIG=1:
//   DEMO_ALLOW_CONFIG=1 docker compose -f docker/docker-compose.yml --profile demo up -d --build demo-app
//   E2E_DEMO_APP=on npx playwright test oidc-demo-app
test.skip(process.env.E2E_DEMO_APP !== "on", "set E2E_DEMO_APP=on with the demo app running");

const DEMO = "http://localhost:4000";
const name = `E2E third-party app ${Date.now()}`;

test("a separate third-party app: consent, deny, refresh, withdraw access, revoke and RP-initiated logout", async ({ page, browser, request }) => {
  test.setTimeout(240_000);
  page.on("dialog", (d) => d.accept());
  await loginAsAdmin(page);
  await page.goto("/admin/oidc-clients");
  await page.getByRole("button", { name: "Add application" }).click();
  await page.locator("#c-name").fill(name);
  await page.getByLabel(/Confidential/).check();
  await page.locator("#c-redirects").fill(`${DEMO}/callback`);
  await page.getByLabel("Refresh tokens (stay signed in)").check();
  await page.locator("#c-logout").fill(`${DEMO}/signed-out`);
  await page.getByRole("button", { name: "Create application" }).click();
  const secret = ((await page.getByTestId("client-secret").innerText()).match(/idf_cs_\S+/) ?? [])[0];
  expect(secret).toBeTruthy();
  await page.getByRole("button", { name: "I have stored it" }).click();
  const card = page.getByTestId("client-list").locator("> div", { hasText: name });
  const clientId = (await card.locator("code.select-all").first().innerText()).trim();
  expect((await request.post(`${DEMO}/_config`, { data: { client_id: clientId, client_secret: secret } })).ok()).toBeTruthy();

  const ctx = await browser.newContext();
  const p = await ctx.newPage();
  p.on("dialog", (d) => d.accept());

  // not signed in -> sign in at Ifora -> consent names the app -> back on the app's own origin
  await p.goto(DEMO);
  await expect(p.getByTestId("signed-out")).toBeVisible();
  await p.getByTestId("signin").click();
  await expect(p).toHaveURL(/\/login\?next=/);
  await p.locator("#email").fill(ADMIN_EMAIL);
  await p.locator("#password").fill(ADMIN_PASSWORD);
  await p.getByRole("button", { name: "Sign In", exact: true }).click();
  await passSecondStep(p);   // the admin has a second factor; the code is single-use
  await expect(p.getByTestId("consent-card")).toContainText(`${name} wants access`);
  await p.getByRole("button", { name: "Allow" }).click();
  await p.waitForURL(`${DEMO}/`);
  await expect(p.getByTestId("welcome")).toContainText("Signed in as");
  await expect(p.getByTestId("claims")).toContainText('"iss": "http://localhost:8000"');
  await expect(p.getByTestId("claims")).toContainText(`"aud": "${clientId}"`);
  await expect(p.getByTestId("userinfo")).toContainText(ADMIN_EMAIL);
  await expect(p.getByTestId("refresh-state")).toHaveText("held");

  // rotation works
  await p.getByTestId("refresh").click();
  await expect(p.getByTestId("notice")).toHaveText("Tokens refreshed.");

  // the user withdraws access in Ifora -> the app's refresh token is dead
  await p.goto("http://localhost:3000/settings");
  await p.getByRole("button", { name: `Withdraw access for ${name}` }).click();
  await expect(p.getByText(`${name} can no longer access your account`)).toBeVisible();
  await p.goto(DEMO);
  await p.getByTestId("refresh").click();
  await expect(p.getByTestId("notice")).toContainText("Refresh failed");

  // signing in again asks for consent again; denying returns the app to a clear error, not a session
  await p.getByTestId("logout").click();            // RP-initiated logout: confirmation page first
  await expect(p.getByTestId("logout-card")).toContainText(`${name} asked to sign you out`);
  await p.getByRole("button", { name: "Sign out" }).click();
  await p.waitForURL((u) => u.origin === DEMO && u.pathname === "/signed-out");
  await expect(p.getByTestId("signed-out-page")).toBeVisible();

  await p.goto(`${DEMO}/login`);
  await p.locator("#email").fill(ADMIN_EMAIL);
  await p.locator("#password").fill(ADMIN_PASSWORD);
  await p.getByRole("button", { name: "Sign In", exact: true }).click();
  await passSecondStep(p);   // the admin has a second factor; the code is single-use
  await expect(p.getByTestId("consent-card")).toContainText(`${name} wants access`);
  await p.getByRole("button", { name: "Deny" }).click();
  await p.waitForURL(`${DEMO}/callback**`);
  await expect(p.getByTestId("error-code")).toHaveText("access_denied");

  // allow this time, then revoke the refresh token from the app
  await p.goto(`${DEMO}/login`);
  await p.getByRole("button", { name: "Allow" }).click();
  await p.waitForURL(`${DEMO}/`);
  await expect(p.getByTestId("refresh-state")).toHaveText("held");
  await p.getByTestId("revoke").click();
  await expect(p.getByTestId("refresh-state")).toHaveText("none");
  await ctx.close();

  // clean up
  await page.goto("/admin/oidc-clients");
  await page.getByTestId("client-list").locator("> div", { hasText: name }).getByRole("button", { name: "Delete" }).last().click();
  await expect(page.getByTestId("client-list")).not.toContainText(name);
});
