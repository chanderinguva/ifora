import { expect, test } from "@playwright/test";
import { loginAsAdmin } from "./helpers";

test("the Okta Expression Language editor suggests attributes and functions and validates as you type", async ({ page }) => {
  await loginAsAdmin(page);
  await page.goto("/admin/group-rules");
  await page.getByRole("button", { name: "Add rule" }).click();
  await page.getByLabel("Okta Expression Language").check();
  const editor = page.locator("#r-expr");
  await editor.click();

  // attributes after "user."
  await editor.pressSequentially("user.");
  const list = page.getByRole("listbox", { name: "Suggestions" });
  await expect(list).toBeVisible();
  await expect(list.getByRole("option", { name: /user\.email/ })).toBeVisible();
  await expect(list.getByRole("option", { name: /user\.login/ })).toBeVisible();
  await expect(list.getByRole("option", { name: /user\.firstName/ })).toHaveCount(0);   // users edit it themselves: never offered
  await editor.pressSequentially("ema");
  await expect(list.getByRole("option")).toHaveCount(1);
  await editor.press("Enter");
  await expect(editor).toHaveValue("user.email");

  // functions after "String." with their documentation
  await editor.press("ControlOrMeta+A");
  await editor.press("Backspace");
  await editor.pressSequentially("String.stringC");
  await expect(page.getByTestId("expression-doc")).toContainText("String.stringContains(text, part)");
  await editor.press("Enter");
  await expect(editor).toHaveValue("String.stringContains()");
  await page.waitForTimeout(150);   // let the editor finish placing the caret inside the parentheses

  // finish the expression by hand; the server validates it live
  await editor.press("ControlOrMeta+A");
  await editor.pressSequentially('String.stringContains(user.email, "@example.com")');
  await editor.press("Escape");
  await expect(page.getByTestId("expression-status")).toContainText("Valid");
  await expect(page.getByTestId("expression-status")).toContainText("user.email");

  // a mistake is explained
  await editor.press("ControlOrMeta+A");
  await editor.pressSequentially("user.department ==");
  await expect(page.getByTestId("expression-status")).toContainText("Expression error");

  // Escape closes the list, Ctrl+Space reopens it
  await editor.press("ControlOrMeta+A");
  await editor.pressSequentially("Str");
  await expect(list).toBeVisible();
  await editor.press("Escape");
  await expect(list).toHaveCount(0);
  await editor.press("Control+Space");
  await expect(list).toBeVisible();
});
