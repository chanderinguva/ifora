import { createHmac } from "crypto";

const B32 = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";

/** RFC 6238 TOTP (SHA-1, 6 digits, 30 s) so the browser test can act as the authenticator app. */
export function totp(secretBase32: string, offsetSeconds = 0): string {
  let bits = "";
  for (const ch of secretBase32.replace(/=+$/, "").toUpperCase()) bits += B32.indexOf(ch).toString(2).padStart(5, "0");
  const key = Buffer.from(bits.match(/.{8}/g)!.map((b) => parseInt(b, 2)));
  const counter = Math.floor((Date.now() / 1000 + offsetSeconds) / 30);
  const buf = Buffer.alloc(8);
  buf.writeBigUInt64BE(BigInt(counter));
  const h = createHmac("sha1", key).update(buf).digest();
  const o = h[h.length - 1] & 0xf;
  const n = ((h[o] & 0x7f) << 24) | (h[o + 1] << 16) | (h[o + 2] << 8) | h[o + 3];
  return String(n % 1_000_000).padStart(6, "0");
}
