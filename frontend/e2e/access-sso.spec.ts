import { expect, test, type Page, type Route } from "@playwright/test";

/**
 * Invitation sign-in (Cloudflare Access). The API's token verification is covered by backend/tests/test_access_sso.py
 * with real signatures; here the Access identity is stubbed at the API boundary so the browser flow can be checked
 * on any stack, whether or not it has Access sign-in switched on.
 */

const USER = { id: 7, email: "friend@example.com", first_name: "friend", last_name: "(guest)", is_admin: false, status: "active" };
const json = (route: Route, body: unknown, status = 200) =>
  route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

type Stub = { enabled?: boolean; accessStatus?: number; firstVisit?: boolean; signedIn?: boolean };

async function stub(page: Page, { enabled = true, accessStatus = 200, firstVisit = false, signedIn = false }: Stub = {}) {
  const calls: string[] = [];
  let session = signedIn; // /me only answers once the invitation sign-in has succeeded
  await page.route("**/api/v1/login/access/enabled", (r) => json(r, { enabled }));
  await page.route("**/api/v1/login/access", (r) => {
    calls.push("login/access");
    if (accessStatus !== 200) return json(r, { detail: "Not signed in through the invitation" }, accessStatus);
    session = true;
    return json(r, { success: true, user: USER, csrf_token: "csrf-stub", first_visit: firstVisit });
  });
  await page.route("**/api/v1/me", (r) =>
    session ? json(r, { authenticated: true, user: USER, csrf_token: "csrf-stub" }) : json(r, { detail: "Not authenticated" }, 401));
  await page.route("**/api/v1/password-policy", (r) => json(r, { rules: ["At least 12 characters"] }));
  return calls;
}

test("returning invited visitor is signed in without seeing the form", async ({ page }) => {
  const calls = await stub(page, { firstVisit: false });
  await page.goto("/login");
  await page.waitForURL(/\/dashboard/);
  expect(calls).toEqual(["login/access"]);
});

test("first visit: choose a password, then skip the passkey", async ({ page }) => {
  await stub(page, { firstVisit: true });
  let body: any = null;
  await page.route("**/api/v1/me/password/initial", (r) => { body = r.request().postDataJSON(); return json(r, { success: true }); });

  await page.goto("/login");
  await page.waitForURL(/\/welcome/);
  await expect(page.getByText(USER.email)).toBeVisible();
  await page.locator("#welcome-pw").fill("A-long-enough-pass1");
  await page.locator("#welcome-pw2").fill("A-different-pass1");
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByText("The passwords do not match")).toBeVisible();
  expect(body).toBeNull();

  await page.locator("#welcome-pw2").fill("A-long-enough-pass1");
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByRole("heading", { name: "Add a passkey" })).toBeVisible();
  expect(body).toEqual({ new_password: "A-long-enough-pass1" });

  await page.getByRole("button", { name: "Skip for now" }).click();
  await page.waitForURL(/\/dashboard/);
});

test("first visit: the passkey step re-sends the password the visitor just chose", async ({ page }) => {
  await stub(page, { firstVisit: true, signedIn: true });
  await page.route("**/api/v1/me/password/initial", (r) => json(r, { success: true }));
  let registerBody: any = null;
  await page.route("**/api/v1/me/passkeys/register/options", (r) => {
    registerBody = r.request().postDataJSON();
    return json(r, { detail: "Passkey limit reached" }, 400);
  });

  await page.goto("/welcome");
  await page.locator("#welcome-pw").fill("A-long-enough-pass1");
  await page.locator("#welcome-pw2").fill("A-long-enough-pass1");
  await page.getByRole("button", { name: "Continue" }).click();
  await page.getByRole("button", { name: "Add a passkey" }).click();
  await expect(page.getByText("Passkey limit reached")).toBeVisible();
  expect(registerBody).toEqual({ password: "A-long-enough-pass1" });
  await expect(page).toHaveURL(/\/welcome/); // stays so they can retry or skip
});

test("welcome without a session goes to the sign-in page", async ({ page }) => {
  await page.route("**/api/v1/me", (r) => json(r, { detail: "Not authenticated" }, 401));
  await page.route("**/api/v1/login/access/enabled", (r) => json(r, { enabled: false }));
  await page.goto("/welcome");
  await page.waitForURL(/\/login/);
});

test("not invited through Access: the normal form is shown", async ({ page }) => {
  await stub(page, { accessStatus: 401 });
  await page.goto("/login");
  await expect(page.getByRole("button", { name: "Sign In", exact: true })).toBeVisible();
  await expect(page.getByTestId("sso-checking")).toHaveCount(0);
});

test("administrators are told to use their password", async ({ page }) => {
  await stub(page, { accessStatus: 403 });
  await page.goto("/login");
  await expect(page.getByRole("button", { name: "Sign In", exact: true })).toBeVisible();
});

test("switched off: the form appears and no sign-in is attempted", async ({ page }) => {
  const calls = await stub(page, { enabled: false });
  await page.goto("/login");
  await expect(page.getByRole("button", { name: "Sign In", exact: true })).toBeVisible();
  expect(calls).toEqual([]);
});

test("an API without the feature (404) behaves like switched off", async ({ page }) => {
  await page.route("**/api/v1/login/access/enabled", (r) => json(r, { detail: "Not Found" }, 404));
  await page.route("**/api/v1/me", (r) => json(r, { detail: "Not authenticated" }, 401));
  await page.goto("/login");
  await expect(page.getByRole("button", { name: "Sign In", exact: true })).toBeVisible();
});

test("right after signing out the visitor is asked before being signed back in", async ({ page }) => {
  const calls = await stub(page, { firstVisit: false });
  await page.addInitScript(() => sessionStorage.setItem("ifora:skip-access-sso", "1"));
  await page.goto("/login");
  await expect(page.getByTestId("sso-continue")).toBeVisible();
  expect(calls).toEqual([]);
  await page.getByTestId("sso-continue").click();
  await page.waitForURL(/\/dashboard/);
  expect(calls).toEqual(["login/access"]);
});
