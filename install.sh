#!/usr/bin/env bash
#
# AntennaMaster — universal self-bootstrapping installer (macOS / Linux).
#
#   ./install.sh              scan the system, install any missing runtimes,
#                             build a self-contained deployment
#   ./install.sh --no-sudo    never invoke sudo (only report manual commands)
#   ./install.sh --yes        assume "yes" to every auto-install prompt
#
# State machine:
#   1. Pre-flight scan   — OS family, CPU arch, package managers, runtimes
#   2. Dependency fetch  — auto-install Python / Node / compilers when missing
#   3. Virtualise & build— .venv + pip, npm ci, Next.js production build
#   4. Graceful failbacks— on any failure, print the exact fix in red and the
#                          copy-paste command to bypass the bottleneck; never
#                          crash the whole run silently.
#
# Intentionally does NOT `set -e`: each step is guarded so a single failure
# yields a helpful hint instead of an opaque abort.
set -uo pipefail
cd "$(dirname "$0")"
ROOT="$(pwd)"

# ---- flags ---------------------------------------------------------------
NO_SUDO=0; ASSUME_YES=0
for a in "$@"; do
  case "$a" in
    --no-sudo) NO_SUDO=1 ;;
    --yes|-y)  ASSUME_YES=1 ;;
    --help|-h) sed -n '2,16p' "$0"; exit 0 ;;
  esac
done
[[ -n "${AM_ASSUME_YES:-}" ]] && ASSUME_YES=1

# ---- colour-coded output -------------------------------------------------
if [[ -t 1 ]]; then
  RED=$'\e[31m'; GRN=$'\e[32m'; YLW=$'\e[33m'; BLU=$'\e[36m'; BLD=$'\e[1m'; RST=$'\e[0m'
else RED=""; GRN=""; YLW=""; BLU=""; BLD=""; RST=""; fi
step() { printf '\n%s\n' "${BLU}${BLD}==>${RST} ${BLD}$*${RST}"; }
ok()   { printf '%s\n' "  ${GRN}✓${RST} $*"; }
warn() { printf '%s\n' "  ${YLW}!${RST} $*"; }
info() { printf '%s\n' "  ${BLU}·${RST} $*"; }
err()  { printf '%s\n' "${RED}${BLD}✗ $*${RST}" >&2; }
hint() { printf '%s\n' "    ${YLW}try:${RST} ${BLD}$*${RST}" >&2; }

FAILED=0
fail() { err "$1"; [[ -n "${2:-}" ]] && hint "$2"; FAILED=1; }

# ---- 1. PRE-FLIGHT SYSTEM SCAN ------------------------------------------
step "1/4  Pre-flight system scan"

OS="unknown"; case "$(uname -s)" in
  Darwin) OS="macos" ;; Linux) OS="linux" ;;
  *) OS="unknown" ;;
esac
ARCH="$(uname -m)"; case "$ARCH" in
  arm64|aarch64) ARCH="arm64" ;; x86_64|amd64) ARCH="x86_64" ;;
esac
ok "OS: ${OS}   Arch: ${ARCH}"

# Detect available package managers (first match wins for auto-install).
PKG=""
for m in brew apt-get dnf yum pacman zypper; do
  if command -v "$m" >/dev/null 2>&1; then PKG="$m"; break; fi
done
[[ -n "$PKG" ]] && ok "Package manager: $PKG" || warn "No supported package manager detected"

# sudo strategy.
SUDO=""
if [[ "$NO_SUDO" -eq 0 && "$(id -u)" -ne 0 ]] && command -v sudo >/dev/null 2>&1; then
  SUDO="sudo"
fi

confirm() {  # $1 = prompt; auto-yes when non-interactive or --yes
  [[ "$ASSUME_YES" -eq 1 || ! -t 0 ]] && return 0
  printf '  %s [Y/n] ' "$1"; read -r reply || return 1
  [[ -z "$reply" || "$reply" =~ ^[Yy] ]]
}

pkg_install() {  # $1 = human name; $2.. = package names to try
  local name="$1"; shift
  [[ -n "$PKG" ]] || { fail "cannot auto-install $name (no package manager)"; return 1; }
  confirm "Install $name with $PKG?" || { warn "skipped $name"; return 1; }
  case "$PKG" in
    brew)    brew install "$@" ;;
    apt-get) $SUDO apt-get update -y && $SUDO apt-get install -y "$@" ;;
    dnf)     $SUDO dnf install -y "$@" ;;
    yum)     $SUDO yum install -y "$@" ;;
    pacman)  $SUDO pacman -S --noconfirm "$@" ;;
    zypper)  $SUDO zypper install -y "$@" ;;
  esac
}

# ---- 2. DYNAMIC DEPENDENCY FETCHING -------------------------------------
step "2/4  Resolving required runtimes"

# --- Python 3.10+ ---
find_python() {
  local c v major minor
  for c in python3.13 python3.12 python3.11 python3.10 python3 python; do
    command -v "$c" >/dev/null 2>&1 || continue
    v="$("$c" -c 'import sys;print("%d.%d"%sys.version_info[:2])' 2>/dev/null || echo 0.0)"
    major="${v%%.*}"; minor="${v##*.}"
    if [[ "$major" -eq 3 && "$minor" -ge 10 ]]; then echo "$c"; return 0; fi
  done
  return 1
}
PYBIN="$(find_python || true)"
if [[ -z "$PYBIN" ]]; then
  warn "Python 3.10+ not found — attempting install"
  case "$PKG" in
    brew)    pkg_install "Python 3.11" python@3.11 ;;
    apt-get) pkg_install "Python 3" python3 python3-venv python3-dev ;;
    dnf|yum) pkg_install "Python 3" python3 python3-devel ;;
    pacman)  pkg_install "Python" python ;;
    zypper)  pkg_install "Python 3" python3 python3-devel ;;
    *) : ;;
  esac
  PYBIN="$(find_python || true)"
fi
if [[ -n "$PYBIN" ]]; then
  ok "Python $("$PYBIN" -c 'import sys;print("%d.%d.%d"%sys.version_info[:3])') ($PYBIN)"
else
  fail "Python 3.10+ is required and could not be installed automatically." \
       "install Python 3.11 from https://www.python.org/downloads/ then re-run ./install.sh"
fi

# --- Node.js 18+ ---
node_ok() { command -v node >/dev/null 2>&1 && \
  [[ "$(node -p 'process.versions.node.split(".")[0]' 2>/dev/null || echo 0)" -ge 18 ]]; }
if ! node_ok; then
  warn "Node.js 18+ not found — attempting install"
  case "$PKG" in
    brew)    pkg_install "Node.js LTS" node ;;
    apt-get)
      if confirm "Install Node.js 20 LTS via NodeSource?"; then
        curl -fsSL https://deb.nodesource.com/setup_20.x | $SUDO -E bash - \
          && $SUDO apt-get install -y nodejs
      fi ;;
    dnf|yum)
      if confirm "Install Node.js 20 LTS via NodeSource?"; then
        curl -fsSL https://rpm.nodesource.com/setup_20.x | $SUDO -E bash - \
          && $SUDO "$PKG" install -y nodejs
      fi ;;
    pacman)  pkg_install "Node.js" nodejs npm ;;
    zypper)  pkg_install "Node.js" nodejs20 ;;
    *) : ;;
  esac
fi
if node_ok; then ok "Node.js $(node -v)  npm $(npm -v 2>/dev/null || echo '?')"
else fail "Node.js 18+ is required and could not be installed automatically." \
          "install the LTS from https://nodejs.org/ then re-run ./install.sh"; fi

# --- Git (recommended) ---
if command -v git >/dev/null 2>&1; then ok "git $(git --version | awk '{print $3}')"
else warn "git not found (optional for running; needed to pull updates)"
     [[ -n "$PKG" ]] && pkg_install "git" git >/dev/null 2>&1 || true; fi

# --- Docker (optional/recommended) ---
if command -v docker >/dev/null 2>&1; then ok "Docker $(docker --version | awk '{print $3}' | tr -d ,) (optional path available)"
else info "Docker not found — optional. 'docker compose up' is an alternative to this installer."; fi

# --- Compiler toolchain (only if a wheel has to be built from source) ---
ensure_build_tools() {
  case "$OS" in
    macos)
      if ! xcode-select -p >/dev/null 2>&1; then
        warn "Xcode Command Line Tools missing — required to compile native wheels"
        confirm "Trigger 'xcode-select --install'?" && xcode-select --install || \
          hint "xcode-select --install"
      fi ;;
    linux)
      if ! command -v cc >/dev/null 2>&1 && ! command -v gcc >/dev/null 2>&1; then
        warn "No C compiler — needed only if a prebuilt wheel is unavailable"
        case "$PKG" in
          apt-get) pkg_install "build tools" build-essential python3-dev ;;
          dnf|yum) pkg_install "build tools" gcc gcc-c++ make python3-devel ;;
          pacman)  pkg_install "build tools" base-devel ;;
          zypper)  pkg_install "build tools" gcc gcc-c++ make ;;
        esac
      fi ;;
  esac
}

# ---- 3. ENVIRONMENT VIRTUALISATION & BUILD ------------------------------
if [[ -n "$PYBIN" ]]; then
  step "3/4  Python virtual environment + backend dependencies"
  if [[ ! -d backend/.venv ]]; then
    if "$PYBIN" -m venv backend/.venv; then ok "Created backend/.venv"
    else fail "could not create the virtualenv" \
              "$PYBIN -m pip install --user virtualenv && $PYBIN -m virtualenv backend/.venv"; fi
  else ok "backend/.venv already present"; fi

  VENV_PY="$ROOT/backend/.venv/bin/python"
  [[ -x "$VENV_PY" ]] || VENV_PY="$ROOT/backend/.venv/Scripts/python.exe"  # git-bash

  if [[ -x "$VENV_PY" ]]; then
    "$VENV_PY" -m pip install --upgrade pip >/dev/null 2>&1 || true
    # First attempt: fast path (manylinux/macos wheels, no compiler needed).
    if "$VENV_PY" -m pip install -r backend/requirements.txt; then
      ok "Backend dependencies installed"
    else
      warn "A dependency failed to install — likely a native build (pyproj/scipy)"
      ensure_build_tools
      if "$VENV_PY" -m pip install -r backend/requirements.txt; then
        ok "Backend dependencies installed (after adding build tools)"
      else
        fail "backend dependencies could not be installed" \
             "activate the venv and inspect the error: source backend/.venv/bin/activate && pip install -r backend/requirements.txt"
      fi
    fi

    # ---- Official ITU-R reference engines (exactness tier, non-fatal) ----
    step "3b/4  ITU-R official reference engines (P.1812 / P.452 / P.2001)"
    # Pinned by commit, matching .github/workflows/ci.yml. These are
    # third-party sources installed with no signature and no lockfile, and
    # they are the very implementations our accuracy claims are measured
    # against - an unpinned branch install would let an upstream change move
    # those numbers, or run arbitrary setup.py code, with nothing on our side
    # to show for it. Keep the two lists in step when bumping.
    ITU_REFS=(
      "Py1812:a5205e6a65db27391a8ba79bd5a365e5391f9fdf"
      "Py452:c047331990d35288300d0865802c98123aa21d3c"
      "Py2001:a4d61a056bad606d1147ff0c441511762ee9fb24"
    )
    itu_ok=1
    for entry in "${ITU_REFS[@]}"; do
      pkg="${entry%%:*}"; ref="${entry##*:}"
      if "$VENV_PY" -m pip show "$pkg" >/dev/null 2>&1; then ok "$pkg already installed"; continue; fi
      if command -v git >/dev/null 2>&1 \
         && "$VENV_PY" -m pip install "$pkg @ git+https://github.com/eeveetza/$pkg@$ref" >/dev/null 2>&1; then
        ok "$pkg installed (pinned ${ref:0:7})"
      elif "$VENV_PY" -m pip install "https://github.com/eeveetza/$pkg/archive/$ref.zip" >/dev/null 2>&1; then
        ok "$pkg installed (pinned ${ref:0:7})"
      else
        warn "$pkg could not be installed (offline?) — exact $pkg studies stay disabled"; itu_ok=0
      fi
    done
    if [[ $itu_ok -eq 1 ]]; then
      info "fetching the ITU integral digital maps from itu.int ..."
      if (cd "$ROOT/backend" && "$VENV_PY" -m tools.fetch_itu_maps); then
        ok "ITU digital maps installed — exact engines ready"
      else
        warn "ITU maps could not be fetched — re-run the installer online to enable the exact engines"
      fi
    fi
  fi
fi

if node_ok; then
  step "3/4  Frontend dependencies + production build"
  if ( cd frontend && { [[ -f package-lock.json ]] && npm ci || npm install; } ); then
    ok "Frontend dependencies installed"
  else
    fail "npm install failed" "cd frontend && rm -rf node_modules package-lock.json && npm install"
  fi
  if ( cd frontend && npm run build ); then
    # Stage the standalone server assets so launch.sh can run it directly.
    if [[ -d frontend/.next/standalone ]]; then
      rm -rf frontend/.next/standalone/.next/static frontend/.next/standalone/public
      cp -r frontend/.next/static frontend/.next/standalone/.next/static 2>/dev/null || true
      [[ -d frontend/public ]] && cp -r frontend/public frontend/.next/standalone/public 2>/dev/null || true
    fi
    ok "Frontend built for production"
  else
    fail "the frontend build failed" "cd frontend && npm run build   # read the first error above"
  fi
fi

# ---- 4. SUMMARY ----------------------------------------------------------
step "4/4  Result"
if [[ "$FAILED" -eq 0 ]]; then
  printf '%s\n\n' "${GRN}${BLD}✓ Install complete.${RST}"
  echo "Start the platform:   ${BLD}./launch.sh${RST}"
  echo "It opens ${BLU}http://localhost:3010${RST} once both servers are healthy."
  exit 0
else
  printf '%s\n' "${RED}${BLD}✗ Install finished with issues (see the red lines above).${RST}"
  echo "Fix the reported step(s) and re-run ${BLD}./install.sh${RST} — completed steps are skipped."
  exit 1
fi
