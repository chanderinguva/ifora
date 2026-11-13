import { expect, test } from "@playwright/test";

const token = "test-only-invitation-token-123456789";

test.beforeEach(async ({ page }) => {
  await page.route("**/api/v1/branding", (route) => route.fulfill({ json: {} }));
});

for (const path of ["/accept-invite", "/reset-password"]) {
  test(`${path}: captures the fragment once under Strict Mode and submits it`, async ({ page }) => {
    let submitted: unknown;
    await page.route("**/api/v1/auth/reset-password", async (route) => {
      submitted = route.request().postDataJSON();
      await route.fulfill({ json: { success: true } });
    });
    await page.goto(`${path}#token=${token}`);
    await expect(page.getByLabel("New password", { exact: true })).toBeVisible();
    await expect(page).toHaveURL(new RegExp(path + "$"));
    await page.waitForTimeout(200); // allow effect replay before checking that the token survived
    await expect(page.getByText("This link is incomplete", { exact: false })).toHaveCount(0);
    await page.getByLabel("New password", { exact: true }).fill("Review-Password-39x!");
    await page.getByLabel("Repeat password").fill("Review-Password-39x!");
    await page.getByRole("button", { name: path === "/accept-invite" ? "Activate account" : "Set password" }).click();
    await expect(page.getByText("Password set. You can sign in now.")).toBeVisible();
    expect(submitted).toEqual({ token, new_password: "Review-Password-39x!" });
    await expect(page.getByRole("link", { name: "Go to sign in" })).toHaveAttribute("href", "/login");
  });
}

test("missing invitation stays in invitation recovery instead of a password-reset loop", async ({ page }) => {
  await page.goto("/accept-invite");
  await expect(page.getByText("This invitation link is incomplete.", { exact: false })).toBeVisible();
  await expect(page.getByRole("link", { name: /Request a new/ })).toHaveCount(0);
  await expect(page.getByText("Need a new invitation?", { exact: false })).toBeVisible();
  await expect(page.getByRole("link", { name: "Back to sign in" })).toBeVisible();
});

test("missing reset token offers a fresh reset link", async ({ page }) => {
  await page.goto("/reset-password");
  await expect(page.getByRole("link", { name: "Request a new password reset link" })).toHaveAttribute("href", "/forgot-password");
});

test("a failed request keeps the form usable, and a retry retains the token", async ({ page }) => {
  let attempts = 0;
  await page.route("**/api/v1/auth/reset-password", async (route) => {
    attempts++;
    if (attempts === 1) return route.abort("failed");
    expect(route.request().postDataJSON().token).toBe(token);
    await route.fulfill({ status: 400, json: { detail: "This link is invalid or has expired" } });
  });
  await page.goto(`/accept-invite#token=${token}`);
  await page.getByLabel("New password", { exact: true }).fill("Review-Password-39x!");
  await page.getByLabel("Repeat password").fill("Review-Password-39x!");
  await page.getByRole("button", { name: "Activate account" }).click();
  await expect(page.getByText("We could not connect to Ifora.", { exact: false })).toBeVisible();
  await expect(page.getByRole("button", { name: "Activate account" })).toBeEnabled();
  await page.getByRole("button", { name: "Activate account" }).click();
  await expect(page.getByText("This invitation is invalid, expired or already used.", { exact: false })).toBeVisible();
});

for (const width of [390, 1280]) {
  test(`My apps edit controls stay inside their card at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1100 });
    await page.route("**/api/v1/me", (route) => route.fulfill({ json: { csrf_token: "test-csrf", user: {
      id: 1, email: "review@example.com", first_name: "Review", last_name: "User",
      is_admin: false, acting_as_user: false, profile_attributes: {},
    } } }));
    await page.route("**/api/v1/me/apps", (route) => route.fulfill({ json: { items: [
      { id: 1, name: "Slack [Inguva Workspace]", description: "", sign_on_mode: "saml", launchable: true, has_icon: true },
    ] } }));
    await page.route("**/api/v1/me/dashboard", (route) => route.fulfill({ json: { sections: [], apps: {}, recent: [1] } }));
    await page.route("**/api/v1/me/apps/1/icon", (route) => route.fulfill({ contentType: "image/svg+xml", body: '<svg xmlns="http://www.w3.org/2000/svg" width="240" height="60"><rect width="240" height="60" fill="purple"/></svg>' }));
    await page.goto("/apps");
    await page.getByTestId("organise-toggle").click();
    const tile = page.getByTestId("tile-1");
    const section = page.getByLabel("Section for Slack [Inguva Workspace]");
    await expect(section).toBeVisible();
    const cardBox = (await tile.boundingBox())!;
    const controlBox = (await section.boundingBox())!;
    const addBox = (await page.getByTestId("add-section").boundingBox())!;
    expect(controlBox.y + controlBox.height).toBeLessThanOrEqual(cardBox.y + cardBox.height);
    expect(addBox.y).toBeGreaterThan(cardBox.y + cardBox.height);
    expect(await tile.locator("img").evaluate((img) => getComputedStyle(img).objectFit)).toBe("contain");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await expect(page.getByTestId("add-section")).toBeDisabled();
    await page.getByLabel("New section name").fill("Work");
    await expect(page.getByTestId("add-section")).toBeEnabled();
    await page.getByTestId("organise-toggle").click();
    await expect(section).toHaveCount(0);
  });
}
