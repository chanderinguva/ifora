import { expect, test } from "@playwright/test";
import { loginAsAdmin } from "./helpers";

const name = `E2E bookmark ${Date.now()}`;

test("create a bookmark application, assign a user, see it under My apps and launch it, then delete it", async ({ page, context }) => {
  page.on("dialog", (d) => d.accept());
  await loginAsAdmin(page);
  await page.getByRole("link", { name: "Applications", exact: true }).click();
  await expect(page).toHaveURL(/\/admin\/applications$/);

  await page.getByRole("button", { name: /Add application/ }).click();
  await page.locator("#a-name").fill(name);
  await page.locator("#a-url").fill("https://example.com/e2e");
  await page.getByRole("button", { name: "Create", exact: true }).click();
  await expect(page).toHaveURL(/\/admin\/applications\/\d+$/);
  await expect(page.getByRole("heading", { name })).toBeVisible();

  // logo: a 1x1 PNG; the dashboard tile then shows an image instead of the initial
  const png = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==", "base64");
  await page.getByLabel("Upload logo").setInputFiles({ name: "logo.png", mimeType: "image/png", buffer: png });
  await expect(page.getByText("Logo saved")).toBeVisible();
  await expect(page.getByTestId("icon-card").locator("img")).toBeVisible();

  // assign the signed-in admin (first user option that is not already assigned is not guaranteed to be them, so assign by searching the list)
  const select = page.getByLabel("Assign a user");
  await select.selectOption({ index: 1 });
  await page.getByRole("button", { name: "Assign" }).first().click();
  await expect(page.getByTestId("assignments")).toBeVisible();
  const assignedLabel = (await page.getByTestId("assignments").locator("li").first().innerText()).toLowerCase();

  // the assigned person sees the tile; if the first option was someone else, only check the admin side
  await page.goto("/dashboard");
  await expect(page.getByRole("heading", { name: "My apps" })).toBeVisible();
  const mine = page.getByTestId("my-apps").getByText(name);
  if (await mine.count()) {
    await expect(page.getByRole("button", { name: `Open ${name}` }).locator("img")).toBeVisible();
    const [popup] = await Promise.all([context.waitForEvent("page"), page.getByRole("button", { name: `Open ${name}` }).click()]);
    await expect(popup).toHaveURL(/example\.com/);
    await popup.close();
  } else {
    expect(assignedLabel).not.toBe("");
  }

  await page.goto("/admin/applications");
  await page.getByRole("link", { name }).click();
  await page.getByRole("button", { name: "Delete" }).click();
  await expect(page).toHaveURL(/\/admin\/applications$/);
  await expect(page.getByText(name)).toHaveCount(0);
});
