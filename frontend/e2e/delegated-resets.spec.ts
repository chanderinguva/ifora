import { expect, test } from "@playwright/test";
import { USER_PASSWORD, login, loginAsAdmin, logout } from "./helpers";

const tag = Date.now();

async function createUser(page: import("@playwright/test").Page, last: string, email: string, admin: boolean) {
  await page.goto("/admin/users");
  await page.getByRole("button", { name: "New user" }).click();
  await page.locator("#nu-first").fill("Reset");
  await page.locator("#nu-last").fill(last);
  await page.locator("#nu-email").fill(email);
  await page.getByLabel("I will set a password").check();
  await page.locator("#nu-pw").fill(USER_PASSWORD);
  if (admin) await page.getByLabel(/administrator/i).first().check();
  await page.getByRole("button", { name: "Create user" }).click();
}

async function open(page: import("@playwright/test").Page, email: string, last: string) {
  await page.goto("/admin/users");
  await page.getByLabel("Search users").fill(email);
  await page.getByRole("link", { name: new RegExp(last) }).first().click();
}

test("a help desk admin can reset an end user's password; a report admin sees the user but cannot", async ({ page }) => {
  page.on("dialog", (d) => d.accept());
  const victimMail = `victim.${tag}@example.com`, deskMail = `desk.${tag}@example.com`, reportMail = `rep.${tag}@example.com`;
  await loginAsAdmin(page);
  await createUser(page, `Victim${tag}`, victimMail, false);
  for (const [last, mail, role] of [[`Desk${tag}`, deskMail, "help_desk_admin"], [`Rep${tag}`, reportMail, "report_admin"]]) {
    await createUser(page, last, mail, true);
    await open(page, mail, last);
    await page.getByTestId(`role-${role}`).check();
    await page.getByTestId("roles-save").click();
    await expect(page.getByText(/Roles saved/)).toBeVisible();
  }
  await logout(page);

  // report admin: can read users, no reset controls, and says why
  await login(page, reportMail, USER_PASSWORD);
  await expect(page).toHaveURL(/\/admin\/dashboard/);
  await open(page, victimMail, `Victim${tag}`);
  await expect(page.getByText(/can view users but not change them/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Reset password" })).toHaveCount(0);
  await logout(page);

  // help desk admin: resets the password; the new one works
  await login(page, deskMail, USER_PASSWORD);
  await expect(page).toHaveURL(/\/admin\/dashboard/);
  await open(page, victimMail, `Victim${tag}`);
  await page.locator("#newpw").fill("Fresh-Desk-Pass-91x");
  await page.getByRole("button", { name: "Reset password" }).click();
  await expect(page.getByText(/Password reset; all of the user's sessions were ended/)).toBeVisible();
  await logout(page);
  await login(page, victimMail, "Fresh-Desk-Pass-91x");
  await expect(page).toHaveURL(/\/dashboard/);
  await logout(page);

  // clean up
  await loginAsAdmin(page);
  for (const [mail, last] of [[victimMail, `Victim${tag}`], [deskMail, `Desk${tag}`], [reportMail, `Rep${tag}`]]) {
    await open(page, mail, last);
    await page.getByRole("button", { name: "Delete user" }).click();
    await expect(page).toHaveURL(/\/admin\/users$/);
  }
});
