import { expect, test } from "@playwright/test";
import { ADMIN_EMAIL, loginAsAdmin } from "./helpers";

test.use({ viewport: { width: 1280, height: 1100 } });
const recipeName = `E2E formulas ${Date.now()}`;

test("write a formula with suggestions, see it as a chip, preview it, run it, and get a clear error for a bad one", async ({ page }) => {
  await loginAsAdmin(page);
  page.on("dialog", (d) => d.accept());
  await page.goto("/admin/recipes");
  await page.getByRole("button", { name: "New recipe" }).click();
  await page.locator("#rc-name").fill(recipeName);
  await page.getByRole("button", { name: "Create and open builder" }).click();
  await page.getByRole("button", { name: "Add a step", exact: true }).first().click();
  await page.getByRole("menuitem", { name: "Write to the job log", exact: true }).click();

  const msg = page.getByLabel("Message", { exact: true });
  await msg.fill("");
  // {{= opens function suggestions; Enter inserts upper() with the cursor inside; then a datapill
  await msg.pressSequentially("Hi {{= upp");
  await expect(page.getByTestId("pill-suggest")).toContainText("upper(text)");
  await page.keyboard.press("Enter");
  await expect(msg).toHaveValue("Hi {{= upper() }}");
  await msg.pressSequentially("trigger.user.ema");
  await page.keyboard.press("Enter");
  await expect(msg).toHaveValue("Hi {{= upper(trigger.user.email) }}");
  await expect(page.getByTestId("formula-chip")).toContainText("ƒ upper(trigger.user.email)");

  // preview needs a sample user (chosen in the Test section)
  await page.getByLabel("Sample user").selectOption({ label: ADMIN_EMAIL });
  await page.getByRole("button", { name: "Preview with the sample" }).click();
  await expect(page.getByTestId("formula-result")).toContainText(ADMIN_EMAIL.toUpperCase());

  // the function list in the tray inserts into the field used last
  await page.getByTestId("formula-functions").locator("summary").click();
  await page.getByLabel("Search functions").fill("round");
  await page.getByTestId("formula-functions").getByRole("button", { name: /round\(number/ }).click();
  await expect(msg).toHaveValue(/round\(\)/);

  // a formula with an unknown datapill is flagged on its chip
  await msg.fill("{{= upper(trigger.nope.x) }}");
  await expect(page.getByTestId("formula-chip")).toHaveAttribute("title", /Not available/);

  // save and dry-run a good formula
  await msg.fill("Hi {{= upper(trigger.user.email) }}");
  await page.getByRole("button", { name: "Save draft" }).click();
  await expect(page.getByTestId("builder-msg")).toContainText("Draft saved");
  await page.getByRole("button", { name: "Run test" }).click();
  await expect(page.getByTestId("job-view")).toContainText(ADMIN_EMAIL.toUpperCase());

  // a formula that does not parse is refused with a message that says where
  await msg.fill("{{= upper( }}");
  await page.getByRole("button", { name: "Save draft" }).click();
  await expect(page.getByTestId("builder-msg")).toContainText("formula");

  await page.goto("/admin/recipes");
  const row = page.getByTestId("recipes-table").locator("tr", { hasText: recipeName });
  await row.getByRole("button", { name: "Delete" }).click();
  await expect(page.getByTestId("recipes-table")).not.toContainText(recipeName);
});
