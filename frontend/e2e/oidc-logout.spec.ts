import { createHash, randomBytes } from "crypto";
import { expect, test } from "@playwright/test";
import { ADMIN_EMAIL, ADMIN_PASSWORD, loginAsAdmin, passSecondStep } from "./helpers";

const name = `E2E logout app ${Date.now()}`;
const CB = "http://localhost:3000/e2e-callback";
const BYE = "http://localhost:3000/e2e-bye";
const verifier = randomBytes(32).toString("base64url");
const challenge = createHash("sha256").update(verifier).digest("base64url");

test("prompt=login forces a new sign-in, and RP-initiated logout confirms, signs out and returns to the app", async ({ page, browser, request }) => {
  test.setTimeout(240_000); // three real sign-ins (each waits for a fresh TOTP step) plus client set-up
  page.on("dialog", (d) => d.accept());
  await loginAsAdmin(page);
  await page.goto("/admin/oidc-clients");
  await page.getByRole("button", { name: "Add application" }).click();
  await page.locator("#c-name").fill(name);
  await page.locator("#c-redirects").fill(CB);
  await page.locator("#c-logout").fill(BYE);
  await page.getByLabel(/First-party/).check();
  await page.getByRole("button", { name: "Create application" }).click();
  const card = page.getByTestId("client-list").locator("> div", { hasText: name });
  const clientId = (await card.locator("code.select-all").first().innerText()).trim();

  const authUrl = (extra: Record<string, string>) =>
    "http://localhost:8000/oauth/authorize?" + new URLSearchParams({
      client_id: clientId, redirect_uri: CB, response_type: "code", scope: "openid", state: "s1", nonce: "n",
      code_challenge: challenge, code_challenge_method: "S256", ...extra,
    });

  const ctx = await browser.newContext();
  const p = await ctx.newPage();
  // signed in via normal SSO first (no prompt): straight back with a code
  await p.goto("http://localhost:3000/login");
  await p.locator("#email").fill(ADMIN_EMAIL);
  await p.locator("#password").fill(ADMIN_PASSWORD);
  await p.getByRole("button", { name: "Sign In", exact: true }).click();
  await passSecondStep(p);   // the admin has a second factor; the code is single-use
  await p.waitForURL(/dashboard/);
  await p.goto(authUrl({}));
  await p.waitForURL(/e2e-callback/);
  expect(new URL(p.url()).searchParams.get("code")).toBeTruthy();

  // prompt=login: the existing session is not enough; the user is sent to sign in again, then returned with a code
  await p.goto(authUrl({ prompt: "login", state: "s2" }));
  await expect(p).toHaveURL(/\/login\?next=/);
  await p.locator("#email").fill(ADMIN_EMAIL);
  await p.locator("#password").fill(ADMIN_PASSWORD);
  await p.getByRole("button", { name: "Sign In", exact: true }).click();
  await passSecondStep(p);   // the admin has a second factor; the code is single-use
  await p.waitForURL(/e2e-callback/);
  const back = new URL(p.url());
  expect(back.searchParams.get("state")).toBe("s2");
  const code = back.searchParams.get("code")!;

  // exchange for an ID token to use as the logout hint
  const tok = await request.post("http://localhost:8000/oauth/token", {
    form: { grant_type: "authorization_code", code, redirect_uri: CB, code_verifier: verifier, client_id: clientId },
  });
  expect(tok.ok()).toBeTruthy();
  const idToken = (await tok.json()).id_token as string;

  // RP-initiated logout: confirmation page, then back to the registered URI with state
  await p.goto("http://localhost:8000/oauth/logout?" + new URLSearchParams({ id_token_hint: idToken, post_logout_redirect_uri: BYE, state: "bye1" }));
  await expect(p.getByTestId("logout-card")).toContainText(name);
  await p.getByRole("button", { name: "Sign out" }).click();
  await p.waitForURL((u) => u.pathname === "/e2e-bye"); // not a substring test: the logout page URL carries it as a parameter
  expect(new URL(p.url()).searchParams.get("state")).toBe("bye1");
  // the session is gone: the same browser context is now rejected by the API
  const me = await p.request.get("http://localhost:8000/api/v1/me");
  expect(me.status()).toBe(401);
  await ctx.close();

  // clean up
  await page.goto("/admin/oidc-clients");
  await page.getByTestId("client-list").locator("> div", { hasText: name }).getByRole("button", { name: "Delete" }).last().click();
  await expect(page.getByTestId("client-list")).not.toContainText(name);
});
