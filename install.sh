#!/usr/bin/env bash
#
# AntennaMaster — one-command local install (Linux / macOS).
#
#   ./install.sh
#
# Checks prerequisites, creates a dedicated Python virtualenv, installs the
# backend and frontend dependencies, and builds the frontend for production.
# Idempotent: safe to re-run.  Launch afterwards with ./launch_simulator.sh
set -euo pipefail
cd "$(dirname "$0")"
ROOT="$(pwd)"

# ---- colour-coded output -------------------------------------------------
if [[ -t 1 ]]; then
  RED=$'\e[31m'; GRN=$'\e[32m'; YLW=$'\e[33m'; BLU=$'\e[36m'; BLD=$'\e[1m'; RST=$'\e[0m'
else
  RED=""; GRN=""; YLW=""; BLU=""; BLD=""; RST=""
fi
step() { printf '%s\n' "${BLU}${BLD}==>${RST} ${BLD}$*${RST}"; }
ok()   { printf '%s\n' "  ${GRN}✓${RST} $*"; }
warn() { printf '%s\n' "  ${YLW}!${RST} $*"; }
die()  { printf '%s\n' "${RED}${BLD}✗ $*${RST}" >&2; exit 1; }

trap 'die "Install failed on line $LINENO. Fix the error above and re-run ./install.sh"' ERR

echo "${BLD}AntennaMaster installer${RST}"
echo "Project: $ROOT"
echo

# ---- 1. prerequisites ----------------------------------------------------
step "Checking prerequisites"

# Python 3.10+
PYBIN=""
for c in python3 python; do
  if command -v "$c" >/dev/null 2>&1; then
    v="$("$c" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || echo 0.0)"
    major="${v%%.*}"; minor="${v##*.}"
    if [[ "$major" -eq 3 && "$minor" -ge 10 ]]; then PYBIN="$c"; break; fi
  fi
done
[[ -n "$PYBIN" ]] || die "Python 3.10+ is required (found none). Install it from https://www.python.org/downloads/"
ok "Python $("$PYBIN" -c 'import sys;print("%d.%d.%d"%sys.version_info[:3])') ($PYBIN)"

command -v node >/dev/null 2>&1 || die "Node.js is required. Install the LTS from https://nodejs.org/"
NODE_MAJOR="$(node -p 'process.versions.node.split(".")[0]')"
[[ "$NODE_MAJOR" -ge 18 ]] || die "Node.js 18+ is required (found $(node -v))."
ok "Node.js $(node -v)"
command -v npm >/dev/null 2>&1 || die "npm was not found (it ships with Node.js)."
ok "npm $(npm -v)"

# ---- 2. python venv ------------------------------------------------------
step "Creating the Python virtual environment (backend/.venv)"
if [[ ! -d backend/.venv ]]; then
  "$PYBIN" -m venv backend/.venv
  ok "Created backend/.venv"
else
  ok "backend/.venv already exists"
fi
# shellcheck disable=SC1091
VENV_PY="$ROOT/backend/.venv/bin/python"
[[ -x "$VENV_PY" ]] || VENV_PY="$ROOT/backend/.venv/Scripts/python.exe"  # git-bash on Windows

# ---- 3. backend deps -----------------------------------------------------
step "Installing backend dependencies"
"$VENV_PY" -m pip install --upgrade pip >/dev/null
"$VENV_PY" -m pip install -r backend/requirements.txt
ok "Backend dependencies installed"

# ---- 4. frontend deps + build --------------------------------------------
step "Installing frontend dependencies (npm)"
( cd frontend && if [[ -f package-lock.json ]]; then npm ci; else npm install; fi )
ok "Frontend dependencies installed"

step "Building the frontend for production (npm run build)"
( cd frontend && npm run build )
# Stage the standalone server's assets so it can be launched directly
# (identical to the Docker runtime; avoids the deprecated `next start` path
# under output:'standalone').
if [[ -d frontend/.next/standalone ]]; then
  rm -rf frontend/.next/standalone/.next/static frontend/.next/standalone/public
  cp -r frontend/.next/static frontend/.next/standalone/.next/static
  [[ -d frontend/public ]] && cp -r frontend/public frontend/.next/standalone/public
fi
ok "Frontend built"

# ---- done ----------------------------------------------------------------
echo
echo "${GRN}${BLD}✓ Install complete.${RST}"
echo
echo "Start the platform with:"
echo "    ${BLD}./launch_simulator.sh${RST}"
echo
echo "It will open ${BLU}http://localhost:3000${RST} in your browser."
