/** @type {import('next').NextConfig} */
const nextConfig = {
  // Trace runtime deps and emit a self-contained server bundle. The Docker
  // runtime stage copies just .next/standalone instead of the full
  // node_modules tree (~700MB → ~150MB).
  output: 'standalone',
  // Lint runs in CI / `npm run lint` — don't break end-user installs over
  // a stray unused import. Type errors still fail the build.
  eslint: { ignoreDuringBuilds: true },
  // Allow cross-origin requests from backend API during development
  allowedDevOrigins: [
    'http://localhost:8742',
    'http://127.0.0.1:8742',
    'http://localhost:3000',
    'http://127.0.0.1:3000',
  ],
  async rewrites() {
    // Rewrites run inside the Next.js server process, so they need an
    // address that *server* can reach. In docker-compose that's the api
    // service hostname (`http://api:8742`), not `localhost:8742` which
    // would resolve back to the frontend container itself and 500.
    // NEXT_PUBLIC_API_URL stays the browser-facing value (baked into the
    // client bundle for direct fetch calls in lib/api.ts) and is the
    // fallback for `next dev` outside docker.
    const apiUrl =
      process.env.INTERNAL_API_URL ||
      process.env.NEXT_PUBLIC_API_URL ||
      'http://localhost:8742';
    return {
      beforeFiles: [
        { source: '/config', destination: `${apiUrl}/config` },
        { source: '/mcp', destination: `${apiUrl}/mcp` },
        { source: '/health', destination: `${apiUrl}/health` },
        { source: '/auth/github', destination: `${apiUrl}/auth/github` },
        { source: '/auth/github/callback', destination: `${apiUrl}/auth/github/callback` },
        { source: '/auth/login', destination: `${apiUrl}/auth/login` },
        { source: '/auth/check', destination: `${apiUrl}/auth/check` },
        { source: '/auth/logout', destination: `${apiUrl}/auth/logout` },
        { source: '/auth/me', destination: `${apiUrl}/auth/me` },
        // Magic-link auth (CLI `delphi open` lands here to set session cookie).
        { source: '/auth/magic/:path*', destination: `${apiUrl}/auth/magic/:path*` },
        { source: '/v1/:path*', destination: `${apiUrl}/v1/:path*` },
      ],
    };
  },
};

export default nextConfig;
