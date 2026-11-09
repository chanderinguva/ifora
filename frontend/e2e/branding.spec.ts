import { expect, test } from "@playwright/test";
import { loginAsAdmin, logout } from "./helpers";

const PNG = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==", "base64");

test("branding: name, colour, logo and message reach the sidebar and the sign-in page; email templates edit and preview", async ({ page }) => {
  await loginAsAdmin(page);
  try {
    await page.goto("/admin/branding");
    await page.locator("#b-name").fill("Acme E2E");
    await page.locator("#b-tag").fill("Welcome back to Acme");
    await page.locator("#b-color").fill("not-a-colour");
    await expect(page.getByTestId("branding-save")).toBeDisabled(); // invalid colour cannot be saved from the UI
    await page.locator("#b-color").fill("#c2185b");
    await page.getByTestId("branding-save").click();
    await expect(page.getByText("Branding saved")).toBeVisible();
    await page.getByLabel("Upload logo").setInputFiles({ name: "logo.png", mimeType: "image/png", buffer: PNG });
    await expect(page.getByText("Logo saved")).toBeVisible();

    // applies across the app
    await page.goto("/admin/dashboard");
    await expect(page.getByTestId("logo-wordmark").first()).toHaveText("Acme E2E");
    await expect(page.getByTestId("logo-image").first()).toBeVisible();
    const primary = await page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue("--primary").trim());
    expect(primary).toMatch(/^3\d\d /); // hue of #c2185b, not the default "222.2 ..."

    // and to anonymous visitors on the sign-in page
    await logout(page);
    await expect(page.getByTestId("logo-wordmark")).toHaveText("Acme E2E");
    await expect(page.getByTestId("login-tagline")).toHaveText("Welcome back to Acme");
    await loginAsAdmin(page);

    // email templates
    await page.goto("/admin/email-templates");
    await page.locator("#t-body").fill("No link in this draft");
    await page.getByTestId("tpl-save").click();
    await expect(page.getByText(/must contain \{\{link\}\}/)).toBeVisible();
    await page.locator("#t-subject").fill("Welcome to {{org_name}}");
    await page.locator("#t-body").fill("Hi {{first_name}}, join {{org_name}}: {{link}}");
    await page.getByTestId("tpl-preview").click();
    await expect(page.getByTestId("tpl-preview-out")).toContainText("Welcome to Acme E2E");
    await expect(page.getByTestId("tpl-preview-out")).toContainText("Hi Alex, join Acme E2E");
    await page.getByTestId("tpl-save").click();
    await expect(page.getByText("Template saved")).toBeVisible();
    await expect(page.getByTestId("tpl-restore")).toBeVisible();
    await page.getByTestId("tpl-restore").click();
    await expect(page.getByText("Reset to the built-in text")).toBeVisible();
  } finally {
    // leave the organization exactly as we found it
    await page.goto("/admin/branding");
    await page.locator("#b-name").fill("");
    await page.locator("#b-tag").fill("");
    await page.locator("#b-color").fill("");
    await page.getByTestId("branding-save").click();
    const remove = page.getByRole("button", { name: "Remove logo" });
    if (await remove.count()) await remove.click();
    await expect(page.getByText(/Logo removed|Branding saved/).first()).toBeVisible();
  }
});
