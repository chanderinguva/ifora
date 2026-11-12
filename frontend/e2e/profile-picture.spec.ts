import { expect, test, type Page, type Route } from "@playwright/test";

/**
 * Profile picture upload. The server side (decoding, size and pixel limits, metadata stripping, access control)
 * is covered by backend/tests/test_avatar.py; here the API is stubbed so the browser flow runs on any stack.
 */

const json = (route: Route, body: unknown, status = 200) =>
  route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

const PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==",
  "base64",
);

const USER = {
  id: 9, email: "pic@example.com", first_name: "Pat", last_name: "Lee", username: "pat.lee",
  is_admin: false, is_super_admin: false, status: "active", profile_attributes: {}, editable_attributes: [],
  mfa_enabled: false, passkey_count: 0, avatar_etag: null as string | null,
};

async function stub(page: Page) {
  const state = { etag: null as string | null, put: null as { type: string | undefined; size: number } | null, deleted: 0 };
  await page.route("**/api/v1/**", (r) => json(r, {}));
  const me = () => ({ ...USER, avatar_etag: state.etag });
  await page.route("**/api/v1/me", (r) => json(r, { authenticated: true, user: me(), csrf_token: "csrf" }));
  await page.route("**/api/v1/me/profile", (r) => json(r, me()));
  await page.route("**/api/v1/me/passkeys", (r) => json(r, { items: [], count: 0, min_for_policy: 2, require_passkey: false }));
  await page.route("**/api/v1/me/sessions", (r) => json(r, { items: [] }));
  await page.route("**/api/v1/me/activity", (r) => json(r, { items: [] }));
  await page.route("**/api/v1/avatars/**", (r) => r.fulfill({ status: 200, contentType: "image/png", body: PNG }));
  await page.route("**/api/v1/me/avatar", async (r) => {
    const req = r.request();
    if (req.method() === "PUT") {
      const body = req.postDataBuffer();
      state.put = { type: req.headers()["content-type"], size: body?.length ?? 0 };
      state.etag = "abc123def4567890";
      return json(r, { avatar_etag: state.etag });
    }
    state.deleted += 1;
    state.etag = null;
    return json(r, { avatar_etag: null });
  });
  return state;
}

test("upload a picture, see it in the header, then remove it", async ({ page }) => {
  const state = await stub(page);
  await page.goto("/settings");
  const box = page.getByTestId("profile-picture");
  await expect(box.getByText("PL", { exact: true })).toBeVisible(); // initials until a picture exists
  await expect(box.getByRole("button", { name: "Upload picture" })).toBeVisible();

  await page.getByTestId("profile-picture-input").setInputFiles({ name: "me.png", mimeType: "image/png", buffer: PNG });
  await expect(box.getByRole("button", { name: "Change picture" })).toBeVisible();
  expect(state.put).toEqual({ type: "image/png", size: PNG.length }); // raw bytes, typed, no multipart
  await expect(box.locator("img")).toHaveAttribute("src", /\/api\/v1\/avatars\/9\?v=abc123def4567890$/);
  await expect(page.getByTestId("user-menu").locator("img")).toBeVisible(); // header updates without a reload

  await box.getByRole("button", { name: "Remove" }).click();
  await expect(box.getByRole("button", { name: "Upload picture" })).toBeVisible();
  await expect(page.getByTestId("user-menu").locator("img")).toHaveCount(0);
  expect(state.deleted).toBe(1);
});

test("a file that is not a supported image is refused before upload", async ({ page }) => {
  const state = await stub(page);
  await page.goto("/settings");
  await page.getByTestId("profile-picture-input").setInputFiles({ name: "x.svg", mimeType: "image/svg+xml", buffer: Buffer.from("<svg/>") });
  await expect(page.getByRole("alert").filter({ hasText: "JPEG, PNG or WebP" })).toBeVisible();
  expect(state.put).toBeNull();
});

test("a server refusal is shown", async ({ page }) => {
  await stub(page);
  await page.route("**/api/v1/me/avatar", (r) => json(r, { detail: "That image is too small; use one at least 64 pixels on each side" }, 422));
  await page.goto("/settings");
  await page.getByTestId("profile-picture-input").setInputFiles({ name: "tiny.png", mimeType: "image/png", buffer: PNG });
  await expect(page.getByRole("alert").filter({ hasText: "too small" })).toBeVisible();
});
