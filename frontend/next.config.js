/** Next.js Configuration */
const nextConfig = {
  reactStrictMode: true,
  swcMinify: true,
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