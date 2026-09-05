import type { NextConfig } from 'next';

const nextConfig: NextConfig = {
  // Emits a self-contained server bundle so the runtime image ships without node_modules.
  output: 'standalone',
  reactStrictMode: true,
  poweredByHeader: false,
  typedRoutes: true,
  experimental: {
    // Server Actions and route handlers receive the browser's Origin header; restricting it here
    // blocks cross-site POSTs that a same-origin cookie session would otherwise authorise.
    serverActions: {
      allowedOrigins: (process.env.ALLOWED_ORIGINS ?? 'localhost:8080').split(','),
    },
  },
};

export default nextConfig;
