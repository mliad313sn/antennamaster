/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Self-contained server bundle for a minimal production Docker image
  // (only the files actually used are traced into .next/standalone).
  output: 'standalone',
  // Proxy API calls to the FastAPI backend so the browser talks to one origin.
  // BACKEND_URL is read at runtime: http://backend:8000 in Docker, or a LAN
  // host in bare-metal deployments.
  async rewrites() {
    const backend = process.env.BACKEND_URL || 'http://localhost:8000';
    return [{ source: '/api/:path*', destination: `${backend}/api/:path*` }];
  },
};

export default nextConfig;
