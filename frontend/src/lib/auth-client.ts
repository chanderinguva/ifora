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
export async function login(email: string, password: string): Promise<{ mfaToken: string } | null> {
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
  if (data.mfa_required) {
    return { mfaToken: data.mfa_token };
  }
  csrfToken = data.csrf_token ?? null;
  return null;
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
export async function loginMfa(mfaToken: string, code: string): Promise<void> {
  const response = await fetch(`${API_URL}/api/v1/login/mfa`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify({ mfa_token: mfaToken, code }),
  });
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || "Verification failed");
  }
  const data = await response.json();
  csrfToken = data.csrf_token ?? null;
}

export async function logout(): Promise<void> {
  if (!csrfToken) {
    await getCurrentUser(); // refreshes the CSRF token after a reload
  }
  const response = await fetch(`${API_URL}/api/v1/logout`, {
    method: "POST",
    credentials: "include",
    headers: { "X-CSRF-Token": csrfToken ?? "" },
  });
  csrfToken = null;

  if (!response.ok) {
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