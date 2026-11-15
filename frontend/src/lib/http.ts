/** Authenticated JSON client for the Ifora API (cookie session + CSRF header). */

import { API_URL } from "./api";
import { ensureCsrfToken } from "./auth-client";
import { askStepUp, STEPUP_REQUIRED } from "./stepup";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

function describe(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((d) => {
        const field = Array.isArray(d?.loc) ? d.loc.filter((x: unknown) => x !== "body").join(".") : "";
        return field ? `${field}: ${d?.msg ?? "invalid"}` : (d?.msg ?? "invalid");
      })
      .join("; ");
  }
  return "Request failed";
}

export async function http<T = any>(
  path: string,
  opts: { method?: string; body?: unknown } = {},
  retried = false,
): Promise<T> {
  const method = opts.method ?? "GET";
  const headers: Record<string, string> = {};
  if (opts.body !== undefined) headers["Content-Type"] = "application/json";
  if (method !== "GET") headers["X-CSRF-Token"] = await ensureCsrfToken();

  const res = await fetch(`${API_URL}/api/v1${path}`, {
    method,
    credentials: "include",
    headers,
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
  });

  let data: any = null;
  try {
    data = await res.json();
  } catch {
    /* empty body */
  }
  if (res.status === 401 && endSession()) return new Promise<T>(() => {});   // the page is leaving; never resolve, so nothing flashes "Not authenticated"
  if (res.status === 403 && data?.detail === STEPUP_REQUIRED && !retried && !path.startsWith("/me/step-up")) {
    // A sensitive administrator action needs a fresh second factor: ask once, then repeat the same request.
    if (await askStepUp()) return http<T>(path, opts, true);
    throw new ApiError(403, "Confirmation with your authenticator was cancelled, so nothing was changed.");
  }
  if (!res.ok) throw new ApiError(res.status, describe(data?.detail));
  return data as T;
}

/** Send one image as the raw request body (the API re-encodes it; no multipart). */
export async function uploadImage<T = any>(path: string, file: Blob): Promise<T> {
  const res = await fetch(`${API_URL}/api/v1${path}`, {
    method: "PUT",
    credentials: "include",
    headers: { "Content-Type": file.type, "X-CSRF-Token": await ensureCsrfToken() },
    body: file,
  });
  let data: any = null;
  try {
    data = await res.json();
  } catch {
    /* empty body */
  }
  if (res.status === 401 && endSession()) return new Promise<T>(() => {});
  if (!res.ok) throw new ApiError(res.status, describe(data?.detail));
  return data as T;
}

let leaving = false;

/** The session ended (timed out or signed out elsewhere): go to the login page and come back here afterwards. Every call here is an authenticated one, so a 401 always means this. */
function endSession(): boolean {
  if (typeof window === "undefined" || window.location.pathname.startsWith("/login")) return false;
  if (!leaving) {
    leaving = true;
    const back = window.location.pathname + window.location.search;
    window.location.assign(`/login?next=${encodeURIComponent(back)}`);
  }
  return true;
}

export function qs(params: Record<string, string | number | undefined | null>): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") sp.set(k, String(v));
  }
  const s = sp.toString();
  return s ? `?${s}` : "";
}

export type Page<T> = { Resources: T[]; totalResults: number; startIndex: number; itemsPerPage: number };
// SCIM-style paging parameters (ADR 025) for a 1-based UI page
export const pageQs = (page: number, size: number) => ({ startIndex: (page - 1) * size + 1, count: size });
