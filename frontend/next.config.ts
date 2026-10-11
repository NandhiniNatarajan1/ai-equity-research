import type { NextConfig } from "next";

const config: NextConfig = {
  reactStrictMode: true,
  async rewrites() {
    // Server-side rewrites run inside the web container, so use the Docker
    // Compose service DNS name (`api`) when running under compose. Falls
    // back to localhost for `npm run dev` outside Docker.
    const apiBase = process.env.API_URL ?? "http://localhost:8000";
    return [{ source: "/api/:path*", destination: `${apiBase}/:path*` }];
  },
};

export default config;
