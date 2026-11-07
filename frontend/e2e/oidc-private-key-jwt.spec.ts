import { createSign, generateKeyPairSync, randomUUID } from "crypto";
import { expect, test } from "@playwright/test";
import { loginAsAdmin } from "./helpers";

const name = `E2E pkjwt ${Date.now()}`;
const API = "https://api.example.com";
const b64u = (b: Buffer | string) => Buffer.from(b).toString("base64url");

test("a client with only a registered public key authenticates with a signed assertion; a replay is refused", async ({ page, request }) => {
  page.on("dialog", (d) => d.accept());
  const { publicKey, privateKey } = generateKeyPairSync("ec", { namedCurve: "P-256" });
  const jwk = { ...publicKey.export({ format: "jwk" }), kid: "e2e-key" };

  await loginAsAdmin(page);
  await page.goto("/admin/oidc-clients");
  await page.getByRole("button", { name: "Add application" }).click();
  await page.locator("#c-name").fill(name);
  await page.getByLabel(/Service/).check();
  await page.getByLabel(/Signed assertion/).check();
  await page.locator("#c-jwks").fill(JSON.stringify({ keys: [{ ...jwk, d: "AAAA" }] }));
  await page.locator("#c-sscopes").fill("reports:read");
  await page.locator("#c-audiences").fill(API);
  await page.getByRole("button", { name: "Create application" }).click();
  await expect(page.getByRole("status")).toContainText(/public keys only/); // private material is refused, nothing stored

  await page.locator("#c-jwks").fill(JSON.stringify({ keys: [jwk] }));
  await page.getByRole("button", { name: "Create application" }).click();
  await expect(page.getByTestId("client-secret")).toHaveCount(0);           // there is no secret to reveal
  const card = page.getByTestId("client-list").locator("> div", { hasText: name });
  await expect(card).toContainText("e2e-key");
  await expect(card).not.toContainText("Client secrets");
  const clientId = (await card.locator("code.select-all").first().innerText()).trim();

  const assertion = () => {
    const t = Math.floor(Date.now() / 1000);
    const head = b64u(JSON.stringify({ alg: "ES256", kid: "e2e-key" }));
    const body = b64u(JSON.stringify({ iss: clientId, sub: clientId, aud: "http://localhost:8000/oauth/token", iat: t, exp: t + 60, jti: randomUUID() }));
    const sig = createSign("SHA256").update(`${head}.${body}`).sign({ key: privateKey, dsaEncoding: "ieee-p1363" });
    return `${head}.${body}.${b64u(sig)}`;
  };
  const form = (a: string) => ({ grant_type: "client_credentials", client_assertion_type: "urn:ietf:params:oauth:client-assertion-type:jwt-bearer", client_assertion: a });

  const a = assertion();
  const ok = await request.post("http://localhost:8000/oauth/token", { form: form(a) });
  expect(ok.ok()).toBeTruthy();
  expect((await ok.json()).scope).toBe("reports:read");
  const replay = await request.post("http://localhost:8000/oauth/token", { form: form(a) });
  expect(replay.status()).toBe(401);
  expect((await replay.json()).error).toBe("invalid_client");

  await card.getByRole("button", { name: "Delete" }).last().click();
  await expect(page.getByTestId("client-list")).not.toContainText(name);
});
