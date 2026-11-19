import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import ApprovePage from "@/app/device/approve/page";
import { fetchPending, forgetDevice, loadDevice, respond, saveDevice } from "@/lib/push-device";

const creds = { id: 7, secret: "s3cret" };
const reply = (status: number, body: unknown = {}) => ({ ok: status >= 200 && status < 300, status, json: async () => body }) as Response;
const request = { pending: true, challenge_id: 3, choices: ["11", "22", "33"], expires_in: 80, requested_from: "1.2.3.4", requested_at: null };

beforeEach(() => {
  // this jsdom setup has no localStorage; give the code under test a small in-memory one
  const store = new Map<string, string>();
  Object.defineProperty(window, "localStorage", {
    configurable: true,
    value: { getItem: (k: string) => store.get(k) ?? null, setItem: (k: string, v: string) => void store.set(k, String(v)), removeItem: (k: string) => void store.delete(k), clear: () => store.clear() },
  });
});
afterEach(() => vi.unstubAllGlobals());

describe("device credentials", () => {
  it("keeps, reads and forgets this browser's device", () => {
    expect(loadDevice()).toBeNull();
    saveDevice(creds);
    expect(loadDevice()).toEqual(creds);
    forgetDevice();
    expect(loadDevice()).toBeNull();
  });
  it("ignores damaged storage", () => {
    window.localStorage.setItem("ifora-push-device", "{nope");
    expect(loadDevice()).toBeNull();
    window.localStorage.setItem("ifora-push-device", JSON.stringify({ id: "x" }));
    expect(loadDevice()).toBeNull();
  });
});

describe("device calls", () => {
  it("sends the device secret as the credential and reports what it learns", async () => {
    const f = vi.fn().mockResolvedValue(reply(200, request));
    vi.stubGlobal("fetch", f);
    expect((await fetchPending(creds))?.choices).toEqual(["11", "22", "33"]);
    expect(f.mock.calls[0][1].headers).toEqual({ Authorization: "Device 7.s3cret" });
    f.mockResolvedValue(reply(200, { pending: false }));
    expect(await fetchPending(creds)).toBeNull();
  });
  it("explains an unregistered browser and an ended request", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(reply(401)));
    await expect(fetchPending(creds)).rejects.toThrow("no longer registered");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(reply(404)));
    await expect(respond(creds, 3, "11")).rejects.toThrow("already ended");
  });
  it("answers with the chosen number, or null for 'this wasn't me'", async () => {
    const f = vi.fn().mockResolvedValue(reply(200, { result: "approved" }));
    vi.stubGlobal("fetch", f);
    expect(await respond(creds, 3, "22")).toBe("approved");
    expect(JSON.parse(f.mock.calls[0][1].body)).toEqual({ challenge_id: 3, number: "22" });
    await respond(creds, 3, null);
    expect(JSON.parse(f.mock.calls[1][1].body)).toEqual({ challenge_id: 3, number: null });
  });
});

describe("approve page", () => {
  it("tells an unregistered browser how to register", async () => {
    render(<ApprovePage />);
    expect(await screen.findByTestId("not-registered")).toBeInTheDocument();
  });

  it("shows the three numbers and sends the one that is tapped", async () => {
    saveDevice(creds);
    const f = vi.fn<(url: string, init?: RequestInit) => Promise<Response>>(async (url) => (url.includes("pending") ? reply(200, request) : reply(200, { result: "approved" })));
    vi.stubGlobal("fetch", f);
    render(<ApprovePage />);
    await userEvent.setup().click(await screen.findByTestId("choice-22"));
    await waitFor(() => expect(screen.getByTestId("approve-done")).toHaveTextContent("Approved"));
    const post = f.mock.calls.find((c) => String(c[0]).includes("respond"))!;
    expect(JSON.parse((post[1] as RequestInit).body as string)).toEqual({ challenge_id: 3, number: "22" });
    expect(screen.queryByTestId("choice-11")).toBeNull(); // one answer per request
  });

  it("declines with 'this wasn't me'", async () => {
    saveDevice(creds);
    vi.stubGlobal("fetch", vi.fn(async (url: string) => (url.includes("pending") ? reply(200, request) : reply(200, { result: "denied" }))));
    render(<ApprovePage />);
    await userEvent.setup().click(await screen.findByTestId("not-me"));
    await waitFor(() => expect(screen.getByTestId("approve-done")).toHaveTextContent("Declined"));
  });

  it("says so when nothing is waiting", async () => {
    saveDevice(creds);
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(reply(200, { pending: false })));
    render(<ApprovePage />);
    expect(await screen.findByText(/No sign-in is waiting/)).toBeInTheDocument();
  });
});
