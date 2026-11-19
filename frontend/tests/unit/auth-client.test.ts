import { beforeEach, describe, expect, it, vi } from "vitest";
import { fail, routes } from "./helpers";

vi.mock("@simplewebauthn/browser", () => ({ startAuthentication: vi.fn(async () => ({ id: "cred" })) }));

import * as client from "@/lib/auth-client";

beforeEach(async () => {
  routes({ "GET /me": { user: null } });
  await client.getCurrentUser(); // resets the in-memory CSRF token
});

describe("sign-in", () => {
  it("a plain sign-in keeps the CSRF token in memory and reports nothing more to do", async () => {
    const r = routes({ "POST /login": { success: true, csrf_token: "tok" } });
    expect(await client.login("a@example.com", "pw")).toBeNull();
    expect(r.calls[0].body).toEqual({ email: "a@example.com", password: "pw" });
    expect(await client.ensureCsrfToken()).toBe("tok");
  });
  it("reports a second step and an expired password", async () => {
    routes({ "POST /login": { mfa_required: true, mfa_token: "m1" } });
    expect(await client.login("a@example.com", "pw")).toEqual({ mfaToken: "m1", factors: ["totp"] });  // an older server names no factors
    routes({ "POST /login": { mfa_required: true, mfa_token: "m2", factors: ["totp", "email"] } });
    expect(await client.login("a@example.com", "pw")).toEqual({ mfaToken: "m2", factors: ["totp", "email"] });
    routes({ "POST /login": { password_change_required: true } });
    expect(await client.login("a@example.com", "pw")).toEqual({ passwordChange: true });
  });
  it("throws the server's reason, or a default", async () => {
    routes({ "POST /login": fail(401, "Invalid credentials") });
    await expect(client.login("a@example.com", "x")).rejects.toThrow("Invalid credentials");
    routes({ "POST /login": new Response(JSON.stringify({}), { status: 500 }) });
    await expect(client.login("a@example.com", "x")).rejects.toThrow("Login failed");
  });
  it("the code step sends the challenge and keeps the new token", async () => {
    const r = routes({ "POST /login/mfa": { csrf_token: "t2" } });
    await client.loginMfa("m1", "123456");
    expect(r.calls[0].body).toEqual({ mfa_token: "m1", code: "123456" });
    expect(await client.ensureCsrfToken()).toBe("t2");
    routes({ "POST /login/mfa": fail(400, "Invalid code") });
    await expect(client.loginMfa("m1", "0")).rejects.toThrow("Invalid code");
    routes({ "POST /login/mfa": new Response("{}", { status: 400 }) });
    await expect(client.loginMfa("m1", "0")).rejects.toThrow("Verification failed");
  });
});

describe("current user and CSRF", () => {
  it("returns the user and remembers the token; a refused call forgets it", async () => {
    routes({ "GET /me": { user: { email: "a@example.com" }, csrf_token: "c9" } });
    expect(await client.getCurrentUser()).toEqual({ email: "a@example.com" });
    expect(await client.ensureCsrfToken()).toBe("c9");
    routes({ "GET /me": new Response("{}", { status: 401 }) });
    expect(await client.getCurrentUser()).toBeNull();
    expect(await client.ensureCsrfToken()).toBe("");
  });
});

describe("sign out", () => {
  it("sends the token, forgets it, and asks before signing back in through an invitation", async () => {
    routes({ "GET /me": { user: {}, csrf_token: "c1" } });
    await client.getCurrentUser();
    const r = routes({ "POST /logout": { ok: true } });
    await client.logout();
    expect((r.fetch.mock.calls[0][1] as RequestInit).headers).toMatchObject({ "X-CSRF-Token": "c1" });
    expect(client.accessSsoSuppressed()).toBe(true);
    client.clearAccessSsoSuppression();
    expect(client.accessSsoSuppressed()).toBe(false);
  });
  it("retries once with a fresh token when the old one was stale", async () => {
    routes({ "GET /me": { user: {}, csrf_token: "old" } });
    await client.getCurrentUser();
    let n = 0;
    routes({ "POST /logout": () => (++n === 1 ? new Response("{}", { status: 403 }) : { ok: true }), "GET /me": { user: {}, csrf_token: "fresh" } });
    await client.logout();
    expect(n).toBe(2);
  });
  it("an already-ended session is fine; anything else is an error", async () => {
    routes({ "POST /logout": new Response("{}", { status: 401 }), "GET /me": new Response("{}", { status: 401 }) });
    await expect(client.logout()).resolves.toBeUndefined();
    routes({ "POST /logout": new Response("{}", { status: 500 }), "GET /me": new Response("{}", { status: 401 }) });
    await expect(client.logout()).rejects.toThrow("Logout failed");
  });
  it("survives storage being unavailable", () => {
    const blocked = () => { throw new Error("blocked"); };
    vi.stubGlobal("sessionStorage", { getItem: blocked, setItem: blocked, removeItem: blocked });
    expect(() => client.suppressAccessSsoOnce()).not.toThrow();
    expect(client.accessSsoSuppressed()).toBe(false);
    expect(() => client.clearAccessSsoSuppression()).not.toThrow();
  });
});

describe("sign in through an invitation", () => {
  it("knows whether the server offers it, and never throws", async () => {
    routes({ "GET /login/access/enabled": { enabled: true } });
    expect(await client.accessSsoEnabled()).toBe(true);
    routes({ "GET /login/access/enabled": { enabled: false } });
    expect(await client.accessSsoEnabled()).toBe(false);
    vi.stubGlobal("fetch", vi.fn(async () => { throw new Error("offline"); }));
    expect(await client.accessSsoEnabled()).toBe(false);
  });
  it("returns whether it was the first visit, or null when it did not work", async () => {
    routes({ "POST /login/access": { csrf_token: "a", first_visit: true } });
    expect(await client.loginWithAccess()).toEqual({ firstVisit: true });
    routes({ "POST /login/access": { csrf_token: "a" } });
    expect(await client.loginWithAccess()).toEqual({ firstVisit: false });
    routes({ "POST /login/access": new Response("{}", { status: 403 }) });
    expect(await client.loginWithAccess()).toBeNull();
    vi.stubGlobal("fetch", vi.fn(async () => { throw new Error("offline"); }));
    expect(await client.loginWithAccess()).toBeNull();
  });
});

describe("passkey sign-in", () => {
  it("runs the ceremony and keeps the token", async () => {
    const r = routes({ "POST /login/passkey/options": { ceremony_id: "cer", options: { challenge: "x" } }, "POST /login/passkey/verify": { csrf_token: "pk" } });
    await client.loginWithPasskey();
    expect(r.calls[1].body).toEqual({ ceremony_id: "cer", credential: { id: "cred" } });
    expect(await client.ensureCsrfToken()).toBe("pk");
  });
  it("explains a cancelled prompt and a server refusal", async () => {
    const web = await import("@simplewebauthn/browser");
    routes({ "POST /login/passkey/options": { ceremony_id: "cer", options: {} } });
    vi.mocked(web.startAuthentication).mockRejectedValueOnce(Object.assign(new Error("x"), { name: "NotAllowedError" }));
    await expect(client.loginWithPasskey()).rejects.toThrow("Passkey sign-in was cancelled.");
    vi.mocked(web.startAuthentication).mockRejectedValueOnce(new Error("other"));
    await expect(client.loginWithPasskey()).rejects.toThrow("Passkey sign-in failed.");
    routes({ "POST /login/passkey/options": fail(503, "Passkeys are off") });
    await expect(client.loginWithPasskey()).rejects.toThrow("Passkeys are off");
    routes({ "POST /login/passkey/options": { ceremony_id: "c", options: {} }, "POST /login/passkey/verify": fail(401, "Unknown passkey") });
    await expect(client.loginWithPasskey()).rejects.toThrow("Unknown passkey");
  });
});

describe("first administrator", () => {
  it("sends the details and the setup key, or throws the reason", async () => {
    const r = routes({ "POST /admin/bootstrap": { ok: true } });
    await client.bootstrapAdmin("a@example.com", "pw", "A", "B", "key");
    expect(r.calls[0].body).toEqual({ email: "a@example.com", password: "pw", first_name: "A", last_name: "B", secret_key: "key" });
    routes({ "POST /admin/bootstrap": fail(403, "Bad key") });
    await expect(client.bootstrapAdmin("a@example.com", "pw", "A", "B", "no")).rejects.toThrow("Bad key");
  });
});
