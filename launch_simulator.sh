#!/usr/bin/env bash
#
# AntennaMaster — production launch wrapper (Linux / macOS).
#
#   ./launch_simulator.sh              start both servers, wait for health,
#                                      open the browser
#   ./launch_simulator.sh --no-browser start without opening a browser
#   ./launch_simulator.sh --service    foreground, no browser (for systemd)
#
# Boots the FastAPI backend (:8000) and the Next.js frontend (:3000) from the
# virtualenv created by install.sh, waits until both answer their health
# checks, then opens the default browser.  Ctrl-C stops both cleanly.
set -euo pipefail
cd "$(dirname "$0")"
ROOT="$(pwd)"

BACKEND_PORT="${BACKEND_PORT:-8010}"
FRONTEND_PORT="${FRONTEND_PORT:-3010}"
HOST_BIND="${HOST_BIND:-0.0.0.0}"       # 0.0.0.0 = reachable on the LAN
OPEN_BROWSER=1
FOREGROUND=0
case "${1:-}" in
  --no-browser) OPEN_BROWSER=0 ;;
  --service)    OPEN_BROWSER=0; FOREGROUND=1 ;;
esac

if [[ -t 1 ]]; then GRN=$'\e[32m'; RED=$'\e[31m'; BLU=$'\e[36m'; BLD=$'\e[1m'; RST=$'\e[0m'
else GRN=""; RED=""; BLU=""; BLD=""; RST=""; fi

VENV_PY="$ROOT/backend/.venv/bin/python"
[[ -x "$VENV_PY" ]] || VENV_PY="$ROOT/backend/.venv/Scripts/python.exe"
[[ -x "$VENV_PY" ]] || { echo "${RED}Not installed. Run ./install.sh first.${RST}" >&2; exit 1; }
[[ -d frontend/.next ]] || { echo "${RED}Frontend not built. Run ./install.sh first.${RST}" >&2; exit 1; }

BACK_PID=""; FRONT_PID=""
cleanup() {
  echo; echo "Stopping…"
  [[ -n "$FRONT_PID" ]] && kill "$FRONT_PID" 2>/dev/null || true
  [[ -n "$BACK_PID" ]] && kill "$BACK_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "${BLD}Starting AntennaMaster…${RST}"

# Backend.
( cd backend && exec "$VENV_PY" -m uvicorn app.main:app \
    --host "$HOST_BIND" --port "$BACKEND_PORT" --workers 2 ) &
BACK_PID=$!

# Frontend: run the standalone Node server (matches the Docker runtime). The
# /api proxy target was baked at build time to localhost:8010 for a same-host
# install, which is correct here.  Falls back to `next start` if the
# standalone build is unavailable.
if [[ -f frontend/.next/standalone/server.js ]]; then
  ( cd frontend/.next/standalone \
      && PORT="$FRONTEND_PORT" HOSTNAME="$HOST_BIND" exec node server.js ) &
else
  ( cd frontend && exec npx next start -p "$FRONTEND_PORT" -H "$HOST_BIND" ) &
fi
FRONT_PID=$!

# ---- wait for health -----------------------------------------------------
wait_up() {  # name url
  local name="$1" url="$2" i
  printf 'Waiting for %s' "$name"
  for i in $(seq 1 60); do
    if curl -fsS -o /dev/null "$url" 2>/dev/null; then printf ' %s\n' "${GRN}ready${RST}"; return 0; fi
    kill -0 "$BACK_PID" 2>/dev/null || { echo " ${RED}backend exited${RST}"; return 1; }
    printf '.'; sleep 1
  done
  printf ' %s\n' "${RED}timeout${RST}"; return 1
}
wait_up "backend " "http://localhost:${BACKEND_PORT}/api/health" || exit 1
wait_up "frontend" "http://localhost:${FRONTEND_PORT}/" || exit 1

URL="http://localhost:${FRONTEND_PORT}"
echo
echo "${GRN}${BLD}AntennaMaster is running.${RST}"
echo "  App:      ${BLU}${URL}${RST}"
echo "  API docs: ${BLU}http://localhost:${BACKEND_PORT}/docs${RST}"
# Show the LAN address so colleagues can reach it.
LAN_IP="$( (hostname -I 2>/dev/null | awk '{print $1}') || true )"
[[ -n "${LAN_IP:-}" ]] && echo "  On the LAN: ${BLU}http://${LAN_IP}:${FRONTEND_PORT}${RST}"
echo "  Stop with Ctrl-C."

# ---- open the browser ----------------------------------------------------
if [[ "$OPEN_BROWSER" -eq 1 ]]; then
  ( if command -v xdg-open >/dev/null 2>&1; then xdg-open "$URL"
    elif command -v open >/dev/null 2>&1; then open "$URL"
    fi ) >/dev/null 2>&1 || true
fi

wait
