// Shared helpers for the k6 scripts (IFORA-59). Nothing here logs a token, a code or a password.
import http from "k6/http";
import { check } from "k6";
import crypto from "k6/crypto";
import encoding from "k6/encoding";
import { Trend } from "k6/metrics";

export const BASE = (__ENV.BASE_URL || "http://host.docker.internal:8310").replace(/\/$/, "");
export const FIXTURE = JSON.parse(open(__ENV.FIXTURE || "/work/.fixture/fixture.json"));

// Per-step latency, so a threshold can target one step ("userinfo p95 < 200 ms") rather than the whole flow.
export const steps = {
  login: new Trend("step_login", true),
  authorize: new Trend("step_authorize", true),
  token: new Trend("step_token", true),
  refresh: new Trend("step_refresh", true),
  userinfo: new Trend("step_userinfo", true),
};

/** Ramp up to VUS over RAMP, hold for DURATION, ramp down. All overridable: VUS, RAMP, DURATION. */
export function stages() {
  const vus = parseInt(__ENV.VUS || "10", 10);
  return [
    { duration: __ENV.RAMP || "20s", target: vus },
    { duration: __ENV.DURATION || "60s", target: vus },
    { duration: "10s", target: 0 },
  ];
}

/** Thresholds shared by every script; a script adds its own on top. Override with P95_MS / MAX_ERROR_RATE. */
export function thresholds(extra) {
  return Object.assign(
    {
      http_req_failed: [`rate<${__ENV.MAX_ERROR_RATE || "0.01"}`],
      checks: [`rate>${1 - parseFloat(__ENV.MAX_ERROR_RATE || "0.01")}`],
    },
    extra || {},
  );
}

export const p95 = (fallback) => `p(95)<${__ENV.P95_MS || fallback}`;

export function userFor(vu) {
  return FIXTURE.users[(vu - 1) % FIXTURE.users.length];
}

function b64url(bytes) {
  return encoding.b64encode(bytes, "rawurl");
}

/** A PKCE pair (RFC 7636, S256). */
export function pkce() {
  const verifier = b64url(crypto.randomBytes(32));
  return { verifier, challenge: b64url(crypto.sha256(verifier, "binary")) };
}

const T = (name, extra) => Object.assign({ tags: { step: name } }, extra || {});

export function login(user) {
  const r = http.post(`${BASE}/api/v1/login`, JSON.stringify({ email: user.email, password: user.password }),
    T("login", { headers: { "Content-Type": "application/json" } }));
  steps.login.add(r.timings.duration);
  const ok = check(r, { "login 200": (x) => x.status === 200 });
  return ok;
}

/** Ask for a code with the browser already signed in (cookie jar). Returns {code, verifier} or null. */
export function authorize(scope) {
  const { verifier, challenge } = pkce();
  const state = b64url(crypto.randomBytes(8));
  const q = [
    ["response_type", "code"], ["client_id", FIXTURE.client_id], ["redirect_uri", FIXTURE.redirect_uri],
    ["scope", scope], ["state", state], ["code_challenge", challenge], ["code_challenge_method", "S256"],
  ].map(([k, v]) => `${k}=${encodeURIComponent(v)}`).join("&");
  const r = http.get(`${BASE}/oauth/authorize?${q}`, T("authorize", { redirects: 0 }));
  steps.authorize.add(r.timings.duration);
  const loc = r.headers["Location"] || "";
  const m = loc.match(/[?&]code=([^&]+)/);
  const ok = check(r, {
    "authorize 303 with a code": (x) => x.status === 303 && !!m,
    "state echoed": () => loc.indexOf(`state=${state}`) !== -1,
  });
  return ok ? { code: decodeURIComponent(m[1]), verifier } : null;
}

/** Public client: client_id in the body, no secret. Returns the parsed token response or null. */
export function exchange(grant) {
  const r = http.post(`${BASE}/oauth/token`, grant, T(grant.grant_type === "refresh_token" ? "refresh" : "token"));
  (grant.grant_type === "refresh_token" ? steps.refresh : steps.token).add(r.timings.duration);
  const body = r.status === 200 ? r.json() : null;
  check(r, { [`${grant.grant_type} 200`]: (x) => x.status === 200 });
  return body;
}

/** The whole sign-in: password login, authorization with PKCE, code exchange. */
export function signIn(user, scope) {
  if (!login(user)) return null;
  const a = authorize(scope);
  if (!a) return null;
  return exchange({
    grant_type: "authorization_code", client_id: FIXTURE.client_id, code: a.code,
    redirect_uri: FIXTURE.redirect_uri, code_verifier: a.verifier,
  });
}

/** Keep the report free of anything secret: only counts and timings, never bodies. */
export function summary(name, data) {
  const out = {};
  out[`/work/results/${name}.json`] = JSON.stringify(data, null, 2);
  return out;
}
