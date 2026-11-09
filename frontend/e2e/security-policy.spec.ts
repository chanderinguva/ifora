import { expect, test } from "@playwright/test";
import { loginAsAdmin } from "./helpers";

test("an administrator tightens the password policy and the rules show on the change-password form", async ({ page }) => {
  await loginAsAdmin(page);
  try {
    await page.goto("/admin/security-policy");
    await page.getByTestId("sp-min").fill("16");
    await page.getByTestId("sp-symbol").check();
    await page.getByTestId("sp-save").click();
    await expect(page.getByRole("status").first()).toContainText("Policy saved");
    await expect(page.getByTestId("sp-rules")).toContainText("At least 16 characters");

    // an idle timeout longer than the session is refused by the server
    await page.getByTestId("sp-life").fill("1");
    await page.getByTestId("sp-idle").fill("120");
    await page.getByTestId("sp-save").click();
    await expect(page.getByRole("alert").or(page.getByRole("status")).first()).toContainText(/idle timeout/i);

    await page.goto("/settings");
    await expect(page.getByTestId("password-rules")).toContainText("At least 16 characters");
    await expect(page.getByTestId("password-rules")).toContainText("At least one symbol");
  } finally {
    await page.goto("/admin/security-policy");
    await page.getByTestId("sp-defaults").click();
    await page.getByTestId("sp-save").click();
    await expect(page.getByRole("status").first()).toContainText("Policy saved");
  }
});
