#!/usr/bin/env bash
# Build the Windows installer (.exe) from Linux/macOS with NSIS.
#
#   ./tools/build_windows_installer.sh
#   -> dist/AntennaMaster-Setup-<version>.exe
#
# Stages a clean application payload (source + web assets + docs, WITHOUT
# runtime caches, virtualenvs, node_modules or build output — the bundled
# install.ps1 bootstrap recreates those on the target machine) and compiles
# packaging/windows/antennamaster.nsi. Requires: nsis, rsync.
set -euo pipefail
cd "$(dirname "$0")/.."

command -v makensis >/dev/null || {
  echo "makensis not found — install NSIS (apt-get install nsis / brew install makensis)"; exit 1; }

STAGE=packaging/windows/stage
rm -rf "$STAGE"
mkdir -p "$STAGE" dist

# --- payload -----------------------------------------------------------
rsync -a backend "$STAGE/" \
  --exclude '.venv' --exclude '__pycache__' --exclude '.pytest_cache' \
  --exclude '/backend/data'   # runtime caches only — keeps backend/app/data
rsync -a frontend "$STAGE/" \
  --exclude 'node_modules' --exclude '.next'
rsync -a docs "$STAGE/" --exclude 'pdf/*.tmp'
cp install.ps1 launch.ps1 install.sh launch.sh \
   INSTALL_GUIDE.md README.md PRECISION_BENCHMARK.md CHANGELOG.md "$STAGE/"

echo "payload: $(du -sh "$STAGE" | cut -f1)"

# --- compile ------------------------------------------------------------
( cd packaging/windows && makensis -V2 antennamaster.nsi )

EXE=$(ls dist/AntennaMaster-Setup-*.exe | tail -1)
echo "built: $EXE ($(du -h "$EXE" | cut -f1))"
file "$EXE"
