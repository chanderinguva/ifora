import { expect, test } from "@playwright/test";
import { loginAsAdmin } from "./helpers";

const tag = Date.now();

test("export users, download the template, check then import a CSV with a bad row, and clean up", async ({ page }) => {
  page.on("dialog", (d) => d.accept());
  await loginAsAdmin(page);
  await page.goto("/admin/users");

  const [exp] = await Promise.all([page.waitForEvent("download"), page.getByTestId("export-csv").click()]);
  expect(exp.suggestedFilename()).toBe("users.csv");
  const exported = (await (await import("fs")).promises.readFile((await exp.path())!, "utf8"));
  expect(exported.split("\r\n")[0]).toContain("first_name");
  expect(exported.split("\r\n")[0]).toContain("groups");

  await page.getByTestId("import-csv").click();
  const [tpl] = await Promise.all([page.waitForEvent("download"), page.getByTestId("download-template").click()]);
  expect(tpl.suggestedFilename()).toBe("users-import-template.csv");

  const csv = [
    "first_name,last_name,username,email,user_type",
    `Csv,One${tag},csv.one${tag},csv.one${tag}@example.com,Employee`,
    `Csv,Two${tag},csv.two${tag},csv.two${tag}@example.com,Intern`,
    `Csv,Bad${tag},csv.bad${tag},not-an-email,Employee`,
  ].join("\r\n");
  await page.getByTestId("csv-file").setInputFiles({ name: "people.csv", mimeType: "text/csv", buffer: Buffer.from(csv) });
  await page.getByTestId("csv-check").click();
  const result = page.getByTestId("csv-result");
  await expect(result).toContainText("2 valid");
  await expect(result).toContainText("1 with problems");
  await expect(result).toContainText("Csv Bad" + tag);
  await page.getByTestId("csv-import").click();
  await expect(result).toContainText("2 created");
  await expect(result).toContainText("staged");

  await page.getByLabel("Search users").fill(`csv.one${tag}`);
  await expect(page.getByRole("link", { name: `Csv One${tag}` })).toBeVisible();
  for (const n of ["One", "Two"]) {
    await page.getByLabel("Search users").fill(`csv.${n.toLowerCase()}${tag}`);
    await page.getByRole("link", { name: `Csv ${n}${tag}` }).click();
    await page.getByRole("button", { name: "Delete user" }).click();
    await expect(page).toHaveURL(/\/admin\/users$/);
  }
});
