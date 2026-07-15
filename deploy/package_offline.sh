#!/usr/bin/env bash
#
# Build the Docker images and export them as a single .tar for air-gapped /
# offline deployment (remote sites, secure industrial networks with no
# registry access).
#
#   ./deploy/package_offline.sh [output.tar]
#
# Produces (default) antennamaster-offline.tar plus a copy of the compose
# file, ready to carry to the target host and load with load_offline.sh.
set -euo pipefail
cd "$(dirname "$0")/.."          # project root

OUT="${1:-antennamaster-offline.tar}"
BACKEND_IMG="antennamaster-backend:latest"
FRONTEND_IMG="antennamaster-frontend:latest"

echo "==> Building images (this may take a few minutes)…"
docker compose build

echo "==> Exporting images to ${OUT}…"
docker save "${BACKEND_IMG}" "${FRONTEND_IMG}" -o "${OUT}"

SIZE="$(du -h "${OUT}" | awk '{print $1}')"
echo
echo "✓ Offline bundle ready: ${OUT} (${SIZE})"
echo
echo "Carry these to the target host:"
echo "    ${OUT}"
echo "    docker-compose.yml"
echo "    deploy/load_offline.sh"
echo
echo "On the target:  ./deploy/load_offline.sh ${OUT}"
