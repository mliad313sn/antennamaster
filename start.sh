#!/usr/bin/env bash
# Launch (or validate) the AntennaMaster RF simulator platform.
#
#   ./start.sh           start backend :8000 + frontend :3000
#   ./start.sh --check   run the full QA gate suite (tests + benchmarks)
set -euo pipefail
cd "$(dirname "$0")"

if [[ "${1:-}" == "--check" ]]; then
  echo "== backend tests =="
  (cd backend && python -m pytest tests/ -q)
  echo "== benchmark gates =="
  (cd backend && python -m benchmarks.bench)
  echo "== frontend tests =="
  (cd frontend && npx vitest run)
  echo "ALL GATES GREEN"
  exit 0
fi

# Ports must match the /api proxy target baked into the frontend build
# (next.config.mjs resolves rewrites at build time), and the banner below must
# match both. Previously this script bound :8000/:3000, the build proxied to
# :8010 and the banner advertised :3010 — three different answers, so every
# API call from the browser failed and the technology dropdown came up empty.
BACKEND_PORT="${BACKEND_PORT:-8010}"
FRONTEND_PORT="${FRONTEND_PORT:-3010}"
export BACKEND_URL="http://localhost:${BACKEND_PORT}"

echo "Starting backend on :${BACKEND_PORT} ..."
(cd backend && exec python -m uvicorn app.main:app --host 0.0.0.0 \
   --port "$BACKEND_PORT" --workers 2) &
BACK_PID=$!

if [[ ! -d frontend/.next ]]; then
  echo "Building frontend (first run) ..."
  (cd frontend && npm run build)
fi
echo "Starting frontend on :${FRONTEND_PORT} ..."
# npm start runs the standalone server; `next start` cannot serve the client
# chunks under output:'standalone' and leaves a blank page.
(cd frontend && PORT="$FRONTEND_PORT" exec npm start) &
FRONT_PID=$!

# Do not print "up" until the API actually answers through the web app - the
# failure this script used to have was invisible precisely because it printed
# success immediately.
echo -n "Waiting for the stack to answer "
for _ in $(seq 1 60); do
  if curl -fsS "http://localhost:${FRONTEND_PORT}/api/health" >/dev/null 2>&1; then
    READY=1; break
  fi
  echo -n "."; sleep 1
done
echo
if [[ "${READY:-0}" != "1" ]]; then
  echo "The web app came up but could not reach the backend through /api." >&2
  echo "If you changed BACKEND_PORT, rebuild the frontend against it:" >&2
  echo "  cd frontend && BACKEND_URL=http://localhost:${BACKEND_PORT} npm run build" >&2
  kill "$BACK_PID" "$FRONT_PID" 2>/dev/null
  exit 1
fi

echo
echo "AntennaMaster is up:  http://localhost:${FRONTEND_PORT}  (API docs: http://localhost:${BACKEND_PORT}/docs)"
echo "Stop with: kill $BACK_PID $FRONT_PID"
wait
