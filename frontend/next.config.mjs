/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Self-contained server bundle for a minimal production Docker image
  // (only the files actually used are traced into .next/standalone).
  output: 'standalone',
  // Proxy API calls to the FastAPI backend so the browser talks to one origin.
  //
  // IMPORTANT: rewrites are resolved at BUILD time and baked into
  // .next/routes-manifest.json - setting BACKEND_URL when *starting* the
  // server has no effect. Point it at the backend before `next build`
  // (docker-compose passes it as a build arg for exactly this reason), and
  // rebuild the frontend if the backend later moves. launch.sh checks the
  // baked value against BACKEND_PORT and refuses to start on a mismatch
  // rather than serving an app whose every API call 500s.
  async rewrites() {
    const backend = process.env.BACKEND_URL || 'http://localhost:8010';
    return [{ source: '/api/:path*', destination: `${backend}/api/:path*` }];
  },
};

export default nextConfig;
