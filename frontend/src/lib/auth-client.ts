/** Authentication client for frontend-to-backend communication. */

import { API_URL } from "./api";

// CSRF token for the current session. Kept in memory only (never in
// localStorage); re-fetched from /me after a page reload.
let csrfToken: string | null = null;

export async function ensureCsrfToken(): Promise<string> {
  if (!csrfToken) {
    await getCurrentUser(); // refreshes the CSRF token after a reload
  }
  return csrfToken ?? "";
}

/** Step 1. Returns an MFA challenge token when a second factor is required, otherwise null (logged in). */
export async function login(email: string, password: string): Promise<{ mfaToken: string; factors: string[] } | { passwordChange: true } | null> {
  const response = await fetch(`${API_URL}/api/v1/login`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    credentials: "include",
    body: JSON.stringify({ email, password }),
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || "Login failed");
  }

  const data = await response.json();
  if (data.password_change_required) {
    return { passwordChange: true };
  }
  if (data.mfa_required) {
    return { mfaToken: data.mfa_token, factors: Array.isArray(data.factors) ? data.factors : ["totp"] };
  }
  csrfToken = data.csrf_token ?? null;
  return null;
}

const SKIP_SSO_KEY = "ifora:skip-access-sso";

/** After signing out, do not silently sign straight back in through the invitation (the Access session outlives ours). */
export function suppressAccessSsoOnce(): void {
  try { sessionStorage.setItem(SKIP_SSO_KEY, "1"); } catch { /* storage unavailable: harmless */ }
}

export function accessSsoSuppressed(): boolean {
  try {
    return sessionStorage.getItem(SKIP_SSO_KEY) === "1";
  } catch {
    return false;
  }
}

/** Forget the sign-out marker once someone has signed in again (not on read: React may run the check twice). */
export function clearAccessSsoSuppression(): void {
  try { sessionStorage.removeItem(SKIP_SSO_KEY); } catch { /* ignore */ }
}

/** Whether this server can sign people in through their invitation (Cloudflare Access). Never throws. */
export async function accessSsoEnabled(): Promise<boolean> {
  try {
    const r = await fetch(`${API_URL}/api/v1/login/access/enabled`, { credentials: "include", signal: AbortSignal.timeout(4000) });
    return r.ok && (await r.json()).enabled === true;
  } catch {
    return false;
  }
}

/** Start a session from the Access identity the browser already holds. Null when it is not available for this person. */
export async function loginWithAccess(): Promise<{ firstVisit: boolean } | null> {
  try {
    const r = await fetch(`${API_URL}/api/v1/login/access`, { method: "POST", credentials: "include" });
    if (!r.ok) return null;
    const data = await r.json();
    csrfToken = data.csrf_token ?? null;
    clearAccessSsoSuppression();
    return { firstVisit: data.first_visit === true };
  } catch {
    return null;
  }
}

/** Passwordless, usernameless sign-in with a discoverable passkey. */
export async function loginWithPasskey(): Promise<void> {
  const { startAuthentication } = await import("@simplewebauthn/browser");
  const opt = await fetch(`${API_URL}/api/v1/login/passkey/options`, { method: "POST", credentials: "include" });
  if (!opt.ok) throw new Error((await opt.json()).detail || "Passkey sign-in is unavailable");
  const { ceremony_id, options } = await opt.json();

  let credential;
  try {
    credential = await startAuthentication(options);
  } catch (e) {
    const name = (e as { name?: string })?.name;
    throw new Error(name === "NotAllowedError" ? "Passkey sign-in was cancelled." : "Passkey sign-in failed.");
  }

  const res = await fetch(`${API_URL}/api/v1/login/passkey/verify`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify({ ceremony_id, credential }),
  });
  if (!res.ok) throw new Error((await res.json()).detail || "Passkey sign-in failed");
  csrfToken = (await res.json()).csrf_token ?? null;
}

/** Step 2: authenticator code or recovery code. */
export async function loginMfa(mfaToken: string, code: string, factor?: "email"): Promise<void> {
  const response = await fetch(`${API_URL}/api/v1/login/mfa`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify({ mfa_token: mfaToken, code, ...(factor ? { factor } : {}) }),
  });
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || "Verification failed");
  }
  const data = await response.json();
  csrfToken = data.csrf_token ?? null;
}

/** Ask for an emailed sign-in code (at most 3 a minute); resolves once the mail is on its way. */
export async function sendEmailCode(mfaToken: string): Promise<void> {
  const response = await fetch(`${API_URL}/api/v1/login/mfa/email/send`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify({ mfa_token: mfaToken }),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || "Could not send the code");
  }
}

export async function logout(): Promise<void> {
  if (!csrfToken) {
    await getCurrentUser(); // refreshes the CSRF token after a reload
  }
  const send = () => fetch(`${API_URL}/api/v1/logout`, {
    method: "POST",
    credentials: "include",
    headers: { "X-CSRF-Token": csrfToken ?? "" },
  });
  let response = await send();
  if (response.status === 403) {
    // stale CSRF token (the session was renewed elsewhere): fetch a fresh one and try once more
    csrfToken = null;
    await getCurrentUser();
    response = await send();
  }
  csrfToken = null;
  suppressAccessSsoOnce();

  // 401 means there is no session any more, which is exactly what the user asked for
  if (!response.ok && response.status !== 401) {
    throw new Error("Logout failed");
  }
}

export async function getCurrentUser(): Promise<any> {
  const response = await fetch(`${API_URL}/api/v1/me`, {
    credentials: "include",
  });

  if (!response.ok) {
    csrfToken = null;
    return null;
  }

  const data = await response.json();
  csrfToken = data.csrf_token ?? null;
  return data.user ?? null;
}

export async function bootstrapAdmin(
  email: string,
  password: string,
  firstName: string,
  lastName: string,
  secret_key: string,
): Promise<void> {
  const response = await fetch(`${API_URL}/api/v1/admin/bootstrap`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      email,
      password,
      first_name: firstName,
      last_name: lastName,
      secret_key,
    }),
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || "Bootstrap failed");
  }
}