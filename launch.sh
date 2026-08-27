#!/usr/bin/env bash
#
# AntennaMaster — one-click launcher wizard (macOS / Linux).
#
#   ./launch.sh               boot both servers, wait for health, open browser
#   ./launch.sh --no-browser  same, without opening a browser
#   ./launch.sh --service     foreground, no browser (systemd / headless)
#
#   1. Verify the environment is intact (.venv + node_modules + build).
#   2. Boot FastAPI (:8010) and Next.js (:3010) concurrently in the background.
#   3. Poll /api/health until both are ready.
#   4. Open the default browser to the portal.
#   5. Trap Ctrl-C / TERM to stop BOTH cleanly — no orphaned ports.
set -uo pipefail
cd "$(dirname "$0")"
ROOT="$(pwd)"

BACKEND_PORT="${BACKEND_PORT:-8010}"
FRONTEND_PORT="${FRONTEND_PORT:-3010}"
HOST_BIND="${HOST_BIND:-0.0.0.0}"
OPEN_BROWSER=1; FOREGROUND=0
case "${1:-}" in
  --no-browser) OPEN_BROWSER=0 ;;
  --service)    OPEN_BROWSER=0; FOREGROUND=1 ;;
  --help|-h)    sed -n '2,12p' "$0"; exit 0 ;;
esac

if [[ -t 1 ]]; then GRN=$'\e[32m'; RED=$'\e[31m'; YLW=$'\e[33m'; BLU=$'\e[36m'; BLD=$'\e[1m'; RST=$'\e[0m'
else GRN=""; RED=""; YLW=""; BLU=""; BLD=""; RST=""; fi
die() { printf '%s\n' "${RED}${BLD}✗ $*${RST}" >&2; exit 1; }

# ---- 1. verify environment health ---------------------------------------
VENV_PY="$ROOT/backend/.venv/bin/python"
[[ -x "$VENV_PY" ]] || VENV_PY="$ROOT/backend/.venv/Scripts/python.exe"
[[ -x "$VENV_PY" ]] || die "Backend virtualenv missing. Run ${BLD}./install.sh${RST} first."
"$VENV_PY" -c 'import fastapi, uvicorn' 2>/dev/null || \
  die "Backend deps incomplete. Re-run ${BLD}./install.sh${RST}."
[[ -d frontend/node_modules ]] || die "frontend/node_modules missing. Run ${BLD}./install.sh${RST}."
[[ -d frontend/.next ]] || die "Frontend not built. Run ${BLD}./install.sh${RST}."

# ---- the build must be newer than the sources it was built from ---------
# Upgrading in place drops new sources next to the PREVIOUS build: the
# installer stages source only, and .next survives from the version before.
# Everything then starts, every route answers 200, and the app the user gets
# is the old one — a failure with no symptom except being wrong. Refuse
# instead, and name the one command that fixes it.
if [[ -f frontend/.next/BUILD_ID ]]; then
  STALE="$(find frontend/app frontend/components frontend/lib frontend/locales \
             frontend/public frontend/next.config.mjs frontend/package.json \
             -newer frontend/.next/BUILD_ID 2>/dev/null | head -1)"
  [[ -z "$STALE" ]] || die "The web app was built before the current sources (e.g. ${BLD}${STALE}${RST}).
Starting now would silently serve the previous version. Rebuild first:
  ${BLD}cd frontend && npm run build${RST}"
fi

# ---- the API proxy target is baked into the build, not read at runtime ---
# Next resolves next.config.mjs rewrites at BUILD time into
# routes-manifest.json, so exporting BACKEND_PORT here cannot move the proxy.
# Without this check the app starts looking perfectly healthy while every API
# call from the browser 500s - the worst possible failure mode.
MANIFEST="frontend/.next/routes-manifest.json"
if [[ -f "$MANIFEST" ]]; then
  BAKED_PORT="$(grep -o 'http://[^"]*/api/:path\*' "$MANIFEST" | head -1 \
    | sed -E 's#.*:([0-9]+)/api.*#\1#')"
  if [[ -n "$BAKED_PORT" && "$BAKED_PORT" != "$BACKEND_PORT" ]]; then
    die "The web app was built to reach the backend on port ${BLD}${BAKED_PORT}${RST}, but BACKEND_PORT is ${BLD}${BACKEND_PORT}${RST}.
The API proxy target is fixed when the frontend is built, so it cannot be changed here.
Rebuild against the port you want:
  ${BLD}cd frontend && BACKEND_URL=http://localhost:${BACKEND_PORT} npm run build${RST}
or launch with ${BLD}BACKEND_PORT=${BAKED_PORT}${RST}."
  fi
fi

# ---- port-in-use guard ---------------------------------------------------
port_busy() { { command -v lsof >/dev/null 2>&1 && lsof -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1; } \
  || { command -v ss >/dev/null 2>&1 && ss -ltn 2>/dev/null | grep -q ":$1 "; }; }
port_busy "$BACKEND_PORT" && die "Port $BACKEND_PORT is already in use (another instance?)."
port_busy "$FRONTEND_PORT" && die "Port $FRONTEND_PORT is already in use."

# ---- 5. clean shutdown of both children ---------------------------------
BACK_PID=""; FRONT_PID=""
cleanup() {
  trap - EXIT INT TERM
  printf '\n%s\n' "Stopping…"
  [[ -n "$FRONT_PID" ]] && kill "$FRONT_PID" 2>/dev/null || true
  [[ -n "$BACK_PID"  ]] && kill "$BACK_PID"  2>/dev/null || true
  # Give them a moment, then hard-kill any stragglers so ports free up.
  sleep 1
  [[ -n "$FRONT_PID" ]] && kill -9 "$FRONT_PID" 2>/dev/null || true
  [[ -n "$BACK_PID"  ]] && kill -9 "$BACK_PID"  2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "${BLD}Starting AntennaMaster…${RST}"

# ---- 2. boot both servers concurrently ----------------------------------
( cd backend && exec "$VENV_PY" -m uvicorn app.main:app \
    --host "$HOST_BIND" --port "$BACKEND_PORT" --workers 2 ) &
BACK_PID=$!

if [[ -f frontend/.next/standalone/server.js ]]; then
  ( cd frontend/.next/standalone \
      && PORT="$FRONTEND_PORT" HOSTNAME="$HOST_BIND" exec node server.js ) &
else
  ( cd frontend && exec npx next start -p "$FRONTEND_PORT" -H "$HOST_BIND" ) &
fi
FRONT_PID=$!

# ---- 3. poll health ------------------------------------------------------
wait_up() {  # name url
  local name="$1" url="$2" i
  printf 'Waiting for %s' "$name"
  for i in $(seq 1 90); do
    if curl -fsS -o /dev/null "$url" 2>/dev/null; then printf ' %s\n' "${GRN}ready${RST}"; return 0; fi
    kill -0 "$BACK_PID"  2>/dev/null || { printf ' %s\n' "${RED}backend exited${RST}"; return 1; }
    kill -0 "$FRONT_PID" 2>/dev/null || { printf ' %s\n' "${RED}frontend exited${RST}"; return 1; }
    printf '.'; sleep 1
  done
  printf ' %s\n' "${RED}timeout${RST}"; return 1
}
wait_up "backend " "http://localhost:${BACKEND_PORT}/api/health" || die "Backend never became healthy — see the log above."
wait_up "frontend" "http://localhost:${FRONTEND_PORT}/"          || die "Frontend never became healthy — see the log above."

URL="http://localhost:${FRONTEND_PORT}"
echo
echo "${GRN}${BLD}AntennaMaster is running.${RST}"
echo "  App:      ${BLU}${URL}${RST}"
echo "  API docs: ${BLU}http://localhost:${BACKEND_PORT}/docs${RST}"
LAN_IP="$( (hostname -I 2>/dev/null | awk '{print $1}') || true )"
[[ -n "${LAN_IP:-}" ]] && echo "  On the LAN: ${BLU}http://${LAN_IP}:${FRONTEND_PORT}${RST}"
echo "  Stop with ${BLD}Ctrl-C${RST}."

# ---- 4. open the browser -------------------------------------------------
if [[ "$OPEN_BROWSER" -eq 1 ]]; then
  ( if   command -v xdg-open >/dev/null 2>&1; then xdg-open "$URL"
    elif command -v open      >/dev/null 2>&1; then open "$URL"
    fi ) >/dev/null 2>&1 || true
fi

# Wait on both; Ctrl-C triggers cleanup via the trap.
wait
