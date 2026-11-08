import { expect, test } from "@playwright/test";
import { loginAsAdmin } from "./helpers";

test("system log: filter, open the detail drawer, save a filter and export CSV", async ({ page }) => {
  await loginAsAdmin(page);
  await page.getByRole("link", { name: "System log", exact: true }).click();
  await expect(page).toHaveURL(/\/admin\/audit$/);
  await expect(page.getByRole("heading", { name: "System log" })).toBeVisible();

  // the action list comes from the API, so newer actions are selectable
  await page.getByLabel("Filter by action").selectOption("LOGIN_SUCCESS");
  await expect(page.getByTestId("audit-table")).toContainText("LOGIN_SUCCESS");

  // detail drawer
  await page.locator("[data-testid^=audit-open-]").first().click();
  await expect(page.getByTestId("audit-drawer")).toBeVisible();
  await expect(page.getByTestId("audit-drawer")).toContainText("Event ID");
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("audit-drawer")).toBeHidden();

  // free-text search narrows to nothing for nonsense
  await page.getByLabel("Search events").fill("zzzz-no-such-event");
  await expect(page.getByTestId("audit-table")).toContainText("No events match");
  await page.getByLabel("Search events").fill("");

  // saved filter (kept in this browser)
  page.once("dialog", (d) => d.accept("Logins"));
  await page.getByTestId("audit-save-filter").click();
  await expect(page.getByTestId("audit-saved")).toContainText("Logins");
  await page.getByRole("button", { name: "Clear" }).click();
  await page.getByTestId("audit-saved").getByRole("button", { name: "Logins", exact: true }).click();
  await expect(page.getByLabel("Filter by action")).toHaveValue("LOGIN_SUCCESS");
  await page.getByRole("button", { name: "Delete saved filter Logins" }).click();
  await expect(page.getByTestId("audit-saved")).toBeHidden();

  // export respects the filter and downloads a CSV
  const [dl] = await Promise.all([page.waitForEvent("download"), page.getByTestId("audit-export").click()]);
  expect(dl.suggestedFilename()).toBe("audit-log.csv");
  const fs = await import("fs");
  const text = fs.readFileSync(await dl.path(), "utf8");
  expect(text.split("\n")[0]).toContain("timestamp");
  expect(text).toContain("LOGIN_SUCCESS");
});
