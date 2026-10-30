import type { NextConfig } from "next";

/**
 * The browser only ever talks to this origin: `/api/*` is rewritten to the FastAPI service, so
 * there is no CORS in production, tokens stay first-party, and the API can live on a private
 * network (a VM, a Colab-tunnelled laptop). Rewrites are resolved at build time, so set API_ORIGIN
 * before `npm run dev` or `npm run build` (see .env.example).
 */
const API_ORIGIN = (process.env.API_ORIGIN ?? "http://127.0.0.1:8000").replace(/\/+$/, "");

const securityHeaders = [
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "X-Frame-Options", value: "SAMEORIGIN" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=(self)" },
];

const nextConfig: NextConfig = {
  cacheComponents: true,
  partialPrefetching: true,
  output: "standalone",
  poweredByHeader: false,
  // Server-Sent Events (/api/v1/events) must not be gzip-buffered on their way through the rewrite.
  compress: false,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API_ORIGIN}/api/:path*` }];
  },
  async headers() {
    return [{ source: "/:path*", headers: securityHeaders }];
  },
};

export default nextConfig;
