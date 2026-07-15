#!/usr/bin/env bash
#
# Load the air-gapped image bundle and start the platform on a target host
# that has Docker but no registry/internet access.
#
#   ./deploy/load_offline.sh [antennamaster-offline.tar]
set -euo pipefail
cd "$(dirname "$0")/.."          # project root

TAR="${1:-antennamaster-offline.tar}"
[[ -f "$TAR" ]] || { echo "Image bundle not found: $TAR" >&2; exit 1; }

echo "==> Loading images from ${TAR}…"
docker load -i "$TAR"

echo "==> Starting the platform…"
# Images are already built/tagged, so compose uses them as-is (no rebuild).
docker compose up -d

echo
echo "✓ AntennaMaster is starting."
echo "  App:  http://localhost:3000"
echo "  Check:  docker compose ps"
