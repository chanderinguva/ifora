import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/auth-client", () => ({ ensureCsrfToken: vi.fn(async () => "csrf-1") }));

import { ApiError, http, pageQs, qs, uploadImage } from "@/lib/http";
import { askStepUp, setStepUpAsker, STEPUP_REQUIRED } from "@/lib/stepup";

const reply = (status: number, body: unknown) => new Response(body === undefined ? null : JSON.stringify(body), { status });

beforeEach(() => setStepUpAsker(null));

describe("http", () => {
  it("sends credentials and no CSRF header on GET", async () => {
    const f = vi.fn(async () => reply(200, { ok: 1 }));
    vi.stubGlobal("fetch", f);
    expect(await http("/me")).toEqual({ ok: 1 });
    const [url, init] = f.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toMatch(/\/api\/v1\/me$/);
    expect(init.credentials).toBe("include");
    expect((init.headers as Record<string, string>)["X-CSRF-Token"]).toBeUndefined();
  });

  it("adds the CSRF token and a JSON body to a write", async () => {
    const f = vi.fn(async () => reply(200, {}));
    vi.stubGlobal("fetch", f);
    await http("/admin/groups", { method: "POST", body: { name: "G" } });
    const init = (f.mock.calls as unknown as [string, RequestInit][])[0][1];
    expect((init.headers as Record<string, string>)["X-CSRF-Token"]).toBe("csrf-1");
    expect((init.headers as Record<string, string>)["Content-Type"]).toBe("application/json");
    expect(init.body).toBe('{"name":"G"}');
  });

  it("turns an error response into an ApiError with the server's message", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => reply(409, { detail: "Already exists" })));
    await expect(http("/x")).rejects.toMatchObject({ status: 409, message: "Already exists" });
    vi.stubGlobal("fetch", vi.fn(async () => reply(422, { detail: [{ loc: ["body", "email"], msg: "bad" }, { msg: "other" }] })));
    await expect(http("/x")).rejects.toThrow("email: bad; other");
    vi.stubGlobal("fetch", vi.fn(async () => reply(500, undefined)));
    await expect(http("/x")).rejects.toThrow("Request failed");
    expect(new ApiError(1, "m")).toBeInstanceOf(Error);
  });

  it("asks for a step-up once and repeats the same request with the same body", async () => {
    const f = vi.fn()
      .mockResolvedValueOnce(reply(403, { detail: STEPUP_REQUIRED }))
      .mockResolvedValueOnce(reply(200, { done: true }));
    vi.stubGlobal("fetch", f);
    const ask = vi.fn(async () => {});
    setStepUpAsker(ask);
    expect(await http("/admin/network-zones", { method: "POST", body: { n: 1 } })).toEqual({ done: true });
    expect(ask).toHaveBeenCalledTimes(1);
    expect(f).toHaveBeenCalledTimes(2);
    expect((f.mock.calls[1][1] as RequestInit).body).toBe('{"n":1}');
  });

  it("does not loop: a second step-up demand after the retry is an error", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => reply(403, { detail: STEPUP_REQUIRED })));
    setStepUpAsker(async () => {});
    await expect(http("/admin/x", { method: "POST", body: {} })).rejects.toBeInstanceOf(ApiError);
  });

  it("a cancelled or unavailable step-up changes nothing and says so", async () => {
    const f = vi.fn(async () => reply(403, { detail: STEPUP_REQUIRED }));
    vi.stubGlobal("fetch", f);
    setStepUpAsker(async () => { throw new Error("cancelled"); });
    await expect(http("/admin/x", { method: "POST", body: {} })).rejects.toThrow(/nothing was changed/);
    setStepUpAsker(null);
    await expect(http("/admin/x", { method: "POST", body: {} })).rejects.toThrow(/nothing was changed/);
    expect(f).toHaveBeenCalledTimes(2); // never retried
  });

  it("never asks about step-up for the step-up endpoint itself", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => reply(403, { detail: STEPUP_REQUIRED })));
    const ask = vi.fn(async () => {});
    setStepUpAsker(ask);
    await expect(http("/me/step-up", { method: "POST", body: { code: "1" } })).rejects.toBeInstanceOf(ApiError);
    expect(ask).not.toHaveBeenCalled();
  });

  it("a 401 sends the person to sign in and never resolves", async () => {
    const assign = vi.fn();
    vi.stubGlobal("location", { pathname: "/admin/users", search: "?q=a", assign });
    vi.stubGlobal("fetch", vi.fn(async () => reply(401, { detail: "Not authenticated" })));
    const settled = vi.fn();
    http("/admin/users").then(settled, settled);
    await new Promise((r) => setTimeout(r, 20));
    expect(assign).toHaveBeenCalledWith("/login?next=%2Fadmin%2Fusers%3Fq%3Da");
    expect(settled).not.toHaveBeenCalled();
  });

  it("a 401 on the login page is an ordinary error", async () => {
    vi.stubGlobal("location", { pathname: "/login", search: "", assign: vi.fn() });
    vi.stubGlobal("fetch", vi.fn(async () => reply(401, { detail: "Invalid credentials" })));
    await expect(http("/me")).rejects.toThrow("Invalid credentials");
  });
});

describe("uploadImage", () => {
  it("sends the raw blob with its type and the CSRF token", async () => {
    const f = vi.fn(async () => reply(200, { ok: true }));
    vi.stubGlobal("fetch", f);
    const blob = new Blob(["x"], { type: "image/png" });
    expect(await uploadImage("/me/avatar", blob)).toEqual({ ok: true });
    const init = (f.mock.calls as unknown as [string, RequestInit][])[0][1];
    expect(init.method).toBe("PUT");
    expect(init.body).toBe(blob);
    expect((init.headers as Record<string, string>)["Content-Type"]).toBe("image/png");
    expect((init.headers as Record<string, string>)["X-CSRF-Token"]).toBe("csrf-1");
  });

  it("reports a refusal", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => reply(415, { detail: "Not an image" })));
    await expect(uploadImage("/me/avatar", new Blob(["x"]))).rejects.toThrow("Not an image");
  });
});

describe("query helpers", () => {
  it("qs drops empty values and encodes the rest", () => {
    expect(qs({ a: 1, b: "", c: undefined, d: null, e: "x y" })).toBe("?a=1&e=x+y");
    expect(qs({})).toBe("");
  });
  it("pageQs turns a 1-based page into SCIM startIndex/count", () => {
    expect(pageQs(1, 25)).toEqual({ startIndex: 1, count: 25 });
    expect(pageQs(3, 25)).toEqual({ startIndex: 51, count: 25 });
  });
});

describe("step-up asker", () => {
  it("is false without a dialog, true after a confirmation, false after a refusal", async () => {
    expect(await askStepUp()).toBe(false);
    setStepUpAsker(async () => {});
    expect(await askStepUp()).toBe(true);
    setStepUpAsker(async () => { throw new Error("no"); });
    expect(await askStepUp()).toBe(false);
  });
});
