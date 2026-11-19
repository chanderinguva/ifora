/** This browser as a push-approval device (IFORA-77): subscription, the device secret kept here, and the two device endpoints. */

import { API_URL } from "./api";

const KEY = "ifora-push-device";

export type DeviceCreds = { id: number; secret: string };
export type PendingRequest = { challenge_id: number; choices: string[]; expires_in: number; requested_from: string | null; requested_at: string | null };

export function pushSupported(): boolean {
  return typeof window !== "undefined" && "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
}

export function loadDevice(): DeviceCreds | null {
  try {
    const raw = window.localStorage.getItem(KEY);
    const d = raw ? JSON.parse(raw) : null;
    return d && typeof d.id === "number" && typeof d.secret === "string" ? d : null;
  } catch {
    return null;
  }
}

export function saveDevice(d: DeviceCreds): void {
  try {
    window.localStorage.setItem(KEY, JSON.stringify(d));
  } catch {
    /* storage blocked: the device cannot answer, and enrolment reports that */
  }
}

export function forgetDevice(): void {
  try {
    window.localStorage.removeItem(KEY);
  } catch {
    /* nothing to forget */
  }
}

function keyBytes(b64url: string): Uint8Array {
  const pad = "=".repeat((4 - (b64url.length % 4)) % 4);
  const raw = atob((b64url + pad).replace(/-/g, "+").replace(/_/g, "/"));
  return Uint8Array.from(raw, (c) => c.charCodeAt(0));
}

/** Ask permission, register the worker and subscribe with the server's application key. Returns the push address. */
export async function subscribe(publicKey: string): Promise<string> {
  if (!pushSupported()) throw new Error("This browser cannot receive push notifications");
  if ((await Notification.requestPermission()) !== "granted") throw new Error("Notifications are blocked for this site. Allow them in the browser settings.");
  const reg = await navigator.serviceWorker.register("/sw.js");
  await navigator.serviceWorker.ready;
  const existing = await reg.pushManager.getSubscription();
  const sub = existing ?? (await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyBytes(publicKey) as BufferSource }));
  return sub.endpoint;
}

const auth = (d: DeviceCreds) => ({ Authorization: `Device ${d.id}.${d.secret}` });

export async function fetchPending(d: DeviceCreds): Promise<PendingRequest | null> {
  const r = await fetch(`${API_URL}/api/v1/device/push/pending`, { headers: auth(d) });
  if (r.status === 401) throw new Error("This browser is no longer registered. Register it again in Account settings.");
  if (!r.ok) throw new Error("Could not check for sign-in requests");
  const body = await r.json();
  return body.pending ? body : null;
}

/** number = null means "this wasn't me". */
export async function respond(d: DeviceCreds, challengeId: number, number: string | null): Promise<"approved" | "denied"> {
  const r = await fetch(`${API_URL}/api/v1/device/push/respond`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...auth(d) },
    body: JSON.stringify({ challenge_id: challengeId, number }),
  });
  if (r.status === 404) throw new Error("That request has already ended");
  if (!r.ok) throw new Error("Could not send your answer");
  return (await r.json()).result;
}
