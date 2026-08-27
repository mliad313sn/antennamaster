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

# A port already in use means an OLDER instance is still listening — and the
# health probe below cannot tell the difference, so this script would print
# "up" while serving the previous version of the app. That is the same silent
# staleness the rebuild check above exists to prevent, one layer down. Refuse.
port_busy() { { command -v lsof >/dev/null 2>&1 && lsof -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1; } \
  || { command -v ss >/dev/null 2>&1 && ss -ltn 2>/dev/null | grep -q ":$1 "; }; }
for p in "$BACKEND_PORT" "$FRONTEND_PORT"; do
  if port_busy "$p"; then
    echo "Port $p is already in use — another AntennaMaster is still running." >&2
    echo "Stop it first, or this script would report success while serving it." >&2
    exit 1
  fi
done

echo "Starting backend on :${BACKEND_PORT} ..."
(cd backend && exec python -m uvicorn app.main:app --host 0.0.0.0 \
   --port "$BACKEND_PORT" --workers 2) &
BACK_PID=$!

# Rebuild when the sources are newer than the build - not only when there is
# no build at all. Serving a stale bundle is the worst failure mode this
# script has: it exits 0, prints "up", every route answers 200, and the app you
# get is the one from before your edit. It cost an hour once; the giveaway was
# a build directory 24 minutes younger than the server process. Next's own
# cache makes an up-to-date rebuild cheap, so the check is allowed to be
# conservative and rebuild when unsure.
needs_build() {
  [[ -f frontend/.next/BUILD_ID ]] || return 0
  local newer
  newer=$(find frontend/app frontend/components frontend/lib frontend/public \
            frontend/next.config.mjs frontend/package.json frontend/locales \
            -newer frontend/.next/BUILD_ID 2>/dev/null | head -1)
  [[ -n "$newer" ]]
}
if needs_build; then
  echo "Frontend sources changed since the last build — rebuilding ..."
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
echo "Stop with Ctrl-C."

# Ctrl-C used to leave both servers running: this script ended on a bare
# `wait`, so the signal reached the shell and the children carried on holding
# the ports - and the port guard above then refused the next start. Descend
# the tree, because `uvicorn --workers 2` is a supervisor with two children
# and killing only the parent orphans them.
kill_tree() {   # kill_tree <signal> <pid>
  local sig="$1" pid="$2" kid
  [[ -n "$pid" ]] || return 0
  for kid in $(pgrep -P "$pid" 2>/dev/null); do kill_tree "$sig" "$kid"; done
  kill "-$sig" "$pid" 2>/dev/null || true
}
stop_all() {
  trap - EXIT INT TERM
  echo; echo "Stopping ..."
  kill_tree TERM "$FRONT_PID"; kill_tree TERM "$BACK_PID"
  sleep 1
  kill_tree KILL "$FRONT_PID"; kill_tree KILL "$BACK_PID"
}
trap stop_all EXIT INT TERM
wait
