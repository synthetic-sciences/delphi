/** @type {import('next').NextConfig} */
const nextConfig = {
  // Allow cross-origin requests from backend API during development
  allowedDevOrigins: [
    'http://localhost:8742',
    'http://127.0.0.1:8742',
    'http://localhost:3000',
    'http://127.0.0.1:3000',
  ],
  async rewrites() {
    const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8742';
    return {
      beforeFiles: [
        { source: '/config', destination: `${apiUrl}/config` },
        { source: '/mcp', destination: `${apiUrl}/mcp` },
        { source: '/health', destination: `${apiUrl}/health` },
        { source: '/auth/github', destination: `${apiUrl}/auth/github` },
        { source: '/auth/github/callback', destination: `${apiUrl}/auth/github/callback` },
        { source: '/auth/login', destination: `${apiUrl}/auth/login` },
        { source: '/auth/me', destination: `${apiUrl}/auth/me` },
        { source: '/v1/:path*', destination: `${apiUrl}/v1/:path*` },
      ],
    };
  },
};

export default nextConfig;
