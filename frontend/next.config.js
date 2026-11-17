/** Next.js Configuration */
// Hostnames (no scheme/port) that may load the dev server's /_next/* resources and HMR WebSocket when it is
// reached through a proxy or tunnel, e.g. IFORA_ALLOWED_DEV_ORIGINS=ifora.app. Next 16 blocks non-localhost origins
// in `next dev`, which leaves the page stuck on "Loading...". Ignored by `next start`.
const allowedDevOrigins = (process.env.IFORA_ALLOWED_DEV_ORIGINS || "")
  .split(",").map((h) => h.trim()).filter(Boolean)

const nextConfig = {
  reactStrictMode: true,
  allowedDevOrigins,
  // Login and consent pages must never be framed (clickjacking).
  async headers() {
    const h = [
      { key: "Content-Security-Policy", value: "frame-ancestors 'none'" },
      { key: "X-Frame-Options", value: "DENY" },
    ];
    const base = [
      { key: "X-Content-Type-Options", value: "nosniff" },
      { key: "Referrer-Policy", value: "no-referrer" },
    ];
    return [{ source: "/:path*", headers: base }, { source: "/login", headers: h }, { source: "/oauth/:path*", headers: h }];
  },
  // Use pages router (not app router) for compatibility
  // experimental: { appDir: false },
}
module.exports = nextConfig