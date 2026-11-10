import { expect, test } from "@playwright/test";
import { USER_PASSWORD, loginAsAdmin } from "./helpers";

// Needs the backend started with PRIMARY_EMAIL_DOMAIN=e2e.example.com (run: PRIMARY_EMAIL_DOMAIN=e2e.example.com ...).
test.skip(process.env.PRIMARY_EMAIL_DOMAIN !== "e2e.example.com", "set PRIMARY_EMAIL_DOMAIN=e2e.example.com on the stack and in this shell");

test("new users get first.last and a primary email; a clash gets a number; a rename changes neither", async ({ page }) => {
  await loginAsAdmin(page);
  const tag = Date.now();
  const last = `Tester${tag}`;
  const base = `naming.tester${tag}`;
  const create = async () => {
    await page.goto("/admin/users");
    await page.getByRole("button", { name: "New user" }).click();
    await page.locator("#nu-first").fill("Naming");
    await page.locator("#nu-last").fill(last);
    return page;
  };

  // first user: username and email are previewed, nothing typed
  await create();
  await expect(page.getByTestId("nu-username")).toHaveAttribute("placeholder", base);
  await expect(page.getByTestId("nu-email-hint")).toContainText(`${base}@e2e.example.com`);
  // user type is a dropdown with the seven fixed values, Employee preselected
  const type = page.locator("#nu-user_type");
  await expect(type).toHaveValue("Employee");
  expect(await type.locator("option").allTextContents()).toEqual(["Not set", "Employee", "Contingent Worker", "Intern", "Service Account", "Test Account", "Shared Account", "Agent Account"]);
  await type.selectOption("Intern");
  await expect(type).toHaveValue("Intern");
  await page.getByLabel("I will set a password").check();
  await page.locator("#nu-pw").fill(USER_PASSWORD);
  await expect(type).toHaveValue("Intern");
  const posted = page.waitForRequest((r) => r.url().endsWith("/admin/users") && r.method() === "POST");
  await page.getByRole("button", { name: "Create user" }).click();
  expect((await posted).postDataJSON().profile_attributes.user_type).toBe("Intern");
  await expect(page.getByLabel("Search users")).toBeVisible();

  // second user with the same name: the preview already shows the next free name
  await create();
  await expect(page.getByTestId("nu-username")).toHaveAttribute("placeholder", `${base}2`);
  await page.getByLabel("I will set a password").check();
  await page.locator("#nu-pw").fill(USER_PASSWORD);
  await page.getByRole("button", { name: "Create user" }).click();
  await expect(page.getByLabel("Search users")).toBeVisible();

  await page.getByLabel("Search users").fill(last);
  await expect(page.getByTestId("users-table")).toContainText(`${base}@e2e.example.com`);
  await expect(page.getByTestId("users-table")).toContainText(`${base}2@e2e.example.com`);

  // rename the first one: username (read-only) and email stay as they were
  await page.getByRole("link", { name: `Naming ${last}`, exact: true }).first().click();
  await page.locator("#last").waitFor();
  const detail = page.url();
  await expect(page.locator("#attr-user_type")).toHaveValue("Intern");
  await expect(page.getByTestId("username-readonly")).toHaveValue(/naming\.tester\d+2?$/);
  const username = await page.getByTestId("username-readonly").inputValue();
  const email = await page.locator("#email").inputValue();
  await page.locator("#last").fill(`Renamed${tag}`);
  await page.getByRole("button", { name: "Save changes" }).click();
  await expect(page.getByText("Saved").first()).toBeVisible();
  await page.goto(detail);
  await page.locator("#last").waitFor({ timeout: 20000 });
  await expect(page.locator("#last")).toHaveValue(`Renamed${tag}`);
  await expect(page.getByTestId("username-readonly")).toHaveValue(username);
  await expect(page.locator("#email")).toHaveValue(email);

  // clean up both users
  for (const q of [`Renamed${tag}`, last]) {
    await page.goto("/admin/users");
    await page.getByLabel("Search users").fill(q);
    await page.getByRole("link", { name: `Naming ${q}`, exact: true }).first().click();
    page.once("dialog", (d) => d.accept());
    await page.getByRole("button", { name: "Delete user" }).click();
    await expect(page).toHaveURL(/\/admin\/users$/);
  }
});
