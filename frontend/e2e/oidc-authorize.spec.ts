import { expect, test } from "@playwright/test";
import { ADMIN_EMAIL, ADMIN_PASSWORD, loginAsAdmin } from "./helpers";

const name = `E2E consent app ${Date.now()}`;
// loopback http is a legal redirect URI and resolves, so the browser really follows the redirect
const CB = "http://localhost:3000/e2e-callback";
const CHALLENGE = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"; // any 43-char base64url value is a valid S256 challenge

test("authorize: sign in on the way, consent screen, allow and deny return to the client", async ({ page, browser }) => {
  page.on("dialog", (d) => d.accept());
  await loginAsAdmin(page);
  await page.goto("/admin/oidc-clients");
  await page.getByRole("button", { name: "Add application" }).click();
  await page.locator("#c-name").fill(name);
  await page.locator("#c-redirects").fill(CB);
  await page.getByRole("button", { name: "Create application" }).click();
  const card = page.getByTestId("client-list").locator("> div", { hasText: name });
  const clientId = (await card.locator("code.select-all").first().innerText()).trim();

  const url = (state: string) =>
    "http://localhost:8000/oauth/authorize?" + new URLSearchParams({
      client_id: clientId, redirect_uri: CB, response_type: "code", scope: "openid profile email", state,
      nonce: "n", code_challenge: CHALLENGE, code_challenge_method: "S256",
    });

  // a visitor with no session: sent to sign in, then back to the consent screen
  const ctx = await browser.newContext();
  const p = await ctx.newPage();
  const landed = async () => { await p.waitForURL(/e2e-callback/); const u = new URL(p.url()); return u; };

  await p.goto(url("s-allow"));
  await expect(p).toHaveURL(/\/login\?next=/);
  await p.locator("#email").fill(ADMIN_EMAIL);
  await p.locator("#password").fill(ADMIN_PASSWORD);
  await p.getByRole("button", { name: "Sign In", exact: true }).click();
  await expect(p.getByTestId("consent-card")).toContainText(`${name} wants access`);
  await expect(p.getByTestId("consent-scopes")).toContainText("Your email address");
  await p.getByRole("button", { name: "Allow" }).click();
  const ok = await landed();
  expect(ok.searchParams.get("state")).toBe("s-allow");
  expect(ok.searchParams.get("code")).toMatch(/^[A-Za-z0-9_-]{40,}$/);
  expect(ok.searchParams.get("iss")).toBe("http://localhost:8000");

  // consent is remembered: no screen the second time
  await p.goto(url("s-again"));
  const again = await landed();
  expect(again.searchParams.get("state")).toBe("s-again");
  expect(again.searchParams.get("code")).toBeTruthy();

  // prompt=consent shows the screen again; denying returns access_denied and no code
  await p.goto(url("s-deny") + "&prompt=consent");
  await p.getByRole("button", { name: "Deny" }).click();
  const denied = await landed();
  expect(denied.searchParams.get("state")).toBe("s-deny");
  expect(denied.searchParams.get("error")).toBe("access_denied");
  expect(denied.searchParams.get("code")).toBeNull();

  // an unregistered redirect URI is never redirected to
  const bad = await p.goto(url("s").replace(encodeURIComponent(CB), encodeURIComponent("https://evil.example.com/cb")));
  expect(bad?.status()).toBe(400);
  expect((await bad?.text())).toContain("redirect URI");
  await ctx.close();

  // clean up
  await page.goto("/admin/oidc-clients");
  await page.getByTestId("client-list").locator("> div", { hasText: name }).getByRole("button", { name: "Delete" }).last().click();
  await expect(page.getByTestId("client-list")).not.toContainText(name);
});
