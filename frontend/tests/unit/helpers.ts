import { vi } from "vitest";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any;
type Handler = (init: RequestInit, url: string) => unknown | Response;
/** Stub fetch with a route table: keys are "METHOD /path-suffix". Unknown routes fail the test loudly. */
export function routes(table: Record<string, Any>) {
  const calls: { method: string; url: string; body: unknown }[] = [];
  const f = vi.fn(async (input: string, init: RequestInit = {}) => {
    const method = (init.method ?? "GET").toUpperCase();
    const path = String(input).replace(/^https?:\/\/[^/]+\/api\/v1/, "").replace(/^https?:\/\/[^/]+/, "");
    calls.push({ method, url: path, body: init.body ? JSON.parse(String(init.body)) : undefined });
    const key = Object.keys(table).find((k) => k.startsWith(method + " ") && (path === k.slice(method.length + 1) || path.startsWith(k.slice(method.length + 1) + "?")));
    if (!key) throw new Error(`unexpected request: ${method} ${path}`);
    const v = table[key];
    const out = typeof v === "function" ? (v as Handler)(init, path) : v;
    return out instanceof Response ? out : new Response(out === undefined ? null : JSON.stringify(out), { status: out === undefined ? 204 : 200 });
  });
  vi.stubGlobal("fetch", f);
  return { calls, fetch: f };
}
export const fail = (status: number, detail: unknown) => new Response(JSON.stringify({ detail }), { status });
