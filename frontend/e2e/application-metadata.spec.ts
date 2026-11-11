import { expect, test } from "@playwright/test";
import { loginAsAdmin } from "./helpers";

const name = `E2E meta ${Date.now()}`;

test("set owner, sensitivity, review date, tags and attributes on an application; they survive a reload", async ({ page }) => {
  page.on("dialog", (d) => d.accept());
  await loginAsAdmin(page);
  await page.getByRole("link", { name: "Applications", exact: true }).click();
  await page.getByRole("button", { name: /Create app integration/ }).click();
  await page.getByTestId("method-bookmark").click();
  await page.getByTestId("wizard-next").click();
  await page.locator("#a-name").fill(name);
  await page.locator("#a-url").fill("https://example.com/meta");
  await page.getByTestId("wizard-create").click();
  await expect(page).toHaveURL(/\/admin\/applications\/\d+$/);

  const meta = page.getByTestId("app-metadata");
  await expect(meta).toBeVisible();
  await meta.locator("#am-owner").selectOption({ index: 1 });
  await meta.locator("#am-sens").selectOption("high");
  await meta.locator("#am-review").fill("2027-03-31");
  await meta.locator("#am-tags").fill("Finance, tier-1");
  await meta.locator("#am-attrs").fill("vendor=Acme\ncost_center=CC-100");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByText("Saved")).toBeVisible();

  await page.reload();
  const again = page.getByTestId("app-metadata");
  await expect(again.locator("#am-sens")).toHaveValue("high");
  await expect(again.locator("#am-review")).toHaveValue("2027-03-31");
  await expect(again.locator("#am-tags")).toHaveValue("finance, tier-1");
  await expect(again.locator("#am-attrs")).toHaveValue("vendor=Acme\ncost_center=CC-100");
  await expect(again.locator("#am-owner")).not.toHaveValue("");   // retries: the owner options load just after the form

  await page.getByRole("button", { name: "Delete" }).click();
  await expect(page).toHaveURL(/\/admin\/applications$/);
});
