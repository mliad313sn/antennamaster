/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Next's built-in gzip BUFFERS a streaming response, and Live Operations is
  // a Server-Sent Events stream proxied through this server. Measured on the
  // running stack: the backend on :8010 answers `content-encoding: identity`
  // and delivers the first frame in 0.0 s, while the same request through
  // :3010 comes back `content-encoding: gzip` and never yields a byte. Every
  // real user goes through this server, so the live twin was permanently
  // blank in every browser - and silently so, because the connection
  // SUCCEEDS, EventSource never fires onerror, and the polling fallback never
  // engaged. `curl` worked throughout, because it does not ask for gzip.
  //
  // Turning Next's compression off costs little here: the API payloads worth
  // compressing (a 2048-sample profile is ~330 KB of JSON) are already gzipped
  // by the backend's own GZipMiddleware and pass through untouched, and any
  // production deployment fronts this with the HTTPS reverse proxy
  // DEPLOYMENT_GUIDE.md requires, which compresses the static shell.
  compress: false,
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
