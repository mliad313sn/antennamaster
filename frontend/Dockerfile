# AntennaMaster frontend — Next.js 14 (standalone output).
# Multi-stage: install deps, build the standalone server, then ship only the
# traced server + static assets on a slim Node runtime.

# ------------------------------------------------------------------- deps
FROM node:20-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

# ---------------------------------------------------------------- builder
FROM node:20-alpine AS builder
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
# Next.js bakes rewrite() destinations at BUILD time, so the API proxy target
# must be known here.  Defaults to the compose service name; override for a
# split-host deployment:  --build-arg BACKEND_URL=http://10.0.0.5:8000
ARG BACKEND_URL=http://backend:8000
ENV BACKEND_URL=$BACKEND_URL
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

# ----------------------------------------------------------------- runner
FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    HOSTNAME=0.0.0.0 \
    PORT=3000 \
    BACKEND_URL=http://backend:8000
RUN addgroup -S app && adduser -S app -G app
# public/ holds the PWA service worker, manifest and icon; static/ the hashed
# assets; standalone/ the minimal Node server that runs the API proxy.
COPY --from=builder /app/public ./public
COPY --from=builder --chown=app:app /app/.next/standalone ./
COPY --from=builder --chown=app:app /app/.next/static ./.next/static
USER app
EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD wget -q -O /dev/null http://127.0.0.1:3000/ || exit 1
CMD ["node", "server.js"]
