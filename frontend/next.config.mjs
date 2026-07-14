/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Proxy API calls to the FastAPI backend so the browser talks to one origin.
  async rewrites() {
    const backend = process.env.BACKEND_URL || 'http://localhost:8000';
    return [{ source: '/api/:path*', destination: `${backend}/api/:path*` }];
  },
};

export default nextConfig;
