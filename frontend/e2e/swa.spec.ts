import { expect, test } from "@playwright/test";
import { loginAsAdmin } from "./helpers";

const TARGET = "http://localhost:9/e2e-login";

// The legacy site is never contacted: the browser's POST to its login URL is intercepted and inspected.
test("SWA application: configure, store a password once, then the tile posts it to the registered login URL", async ({ page }) => {
  page.on("dialog", (d) => d.accept());
  const posts: string[] = [];
  await page.route(TARGET, async (route) => {
    posts.push(route.request().postData() ?? "");
    await route.fulfill({ status: 200, contentType: "text/html", body: "<html><body>legacy site reached</body></html>" });
  });

  await loginAsAdmin(page);
  const name = `E2E SWA ${Date.now()}`;
  await page.goto("/admin/applications");
  await page.getByRole("button", { name: /Create app integration/ }).click();
  await page.getByTestId("method-swa").click();
  await page.getByTestId("wizard-next").click();
  await page.locator("#a-name").fill(name);
  await page.locator("#a-login").fill(TARGET);
  await page.locator("#a-uf").fill("login_user");
  await page.locator("#a-pf").fill("login_pass");
  await page.getByTestId("wizard-create").click();
  await expect(page).toHaveURL(/\/admin\/applications\/(\d+)$/);
  const appId = page.url().split("/").pop()!;

  await page.getByTestId("tab-signon").click();
  await page.locator("#swa-url").fill(TARGET);
  await page.locator("#swa-uf").fill("login_user");
  await page.locator("#swa-pf").fill("login_pass");
  await page.getByRole("button", { name: "Add field" }).click();
  await page.getByLabel("Extra field 1 name").fill("do");
  await page.getByLabel("Extra field 1 value").fill("login");
  await page.getByRole("button", { name: "Save SWA settings" }).click();
  await expect(page.getByText("SWA settings saved")).toBeVisible();

  // assign the signed-in throwaway admin (SWA always requires an assignment)
  await page.getByTestId("tab-assignments").click();
  const select = page.getByLabel("Assign a user");
  const value = await select.locator("option", { hasText: process.env.ADMIN_EMAIL ?? "e2e.throwaway@example.com" }).first().getAttribute("value");
  await select.selectOption(value!);
  await page.getByRole("button", { name: "Assign" }).first().click();
  await expect(page.getByTestId("assignments")).toBeVisible();

  // first launch asks for the account, then posts it
  await page.goto(`/swa/continue?app=${appId}`);
  await expect(page.getByTestId("swa-continue")).toContainText("Connect your");
  await page.locator("#swa-user").fill("legacy.jdoe");
  await page.locator("#swa-pass").fill("Legacy-Secret-42");
  await page.getByRole("button", { name: "Save and sign in" }).click();
  await expect.poll(() => posts.length).toBe(1);
  const form = new URLSearchParams(posts[0]);
  expect(form.get("do")).toBe("login");
  expect(form.get("login_user")).toBe("legacy.jdoe");
  expect(form.get("login_pass")).toBe("Legacy-Secret-42");
  await expect(page.getByText("legacy site reached")).toBeVisible();

  // the next launch needs no typing, and the password is not in the page, the URL or the status response
  await page.goto(`/swa/continue?app=${appId}`);
  await expect.poll(() => posts.length).toBe(2);
  expect(new URLSearchParams(posts[1]).get("login_pass")).toBe("Legacy-Secret-42");
  await page.goto("/dashboard"); // the page is the (intercepted) legacy site until we leave it
  const status = await page.evaluate(async (id) => (await fetch(`http://localhost:8000/api/v1/swa/apps/${id}`, { credentials: "include" })).text(), appId);
  expect(status).not.toContain("Legacy-Secret-42");

  // the admin sees that a sign-in is stored (never the password) and can reset it
  await page.goto(`/admin/applications/${appId}`);
  await page.getByTestId("tab-signon").click();
  await expect(page.getByTestId("swa-credentials")).toContainText("legacy.jdoe");
  await expect(page.getByTestId("swa-credentials")).not.toContainText("Legacy-Secret-42");
  await page.getByRole("button", { name: "Reset" }).click();
  await expect(page.getByTestId("swa-credentials")).toContainText("No user has stored a password yet");

  await page.goto(`/swa/continue?app=${appId}`);
  await expect(page.getByTestId("swa-continue")).toContainText("Connect your");
  expect(posts.length).toBe(2);

  await page.goto(`/admin/applications/${appId}`);
  await page.getByRole("button", { name: "Delete" }).click();
  await expect(page).toHaveURL(/\/admin\/applications$/);
});
