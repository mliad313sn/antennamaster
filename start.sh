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

echo "Starting backend on :8000 ..."
(cd backend && exec python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2) &
BACK_PID=$!

if [[ ! -d frontend/.next ]]; then
  echo "Building frontend (first run) ..."
  (cd frontend && npm run build)
fi
echo "Starting frontend on :3000 ..."
(cd frontend && exec npx next start -p 3000) &
FRONT_PID=$!

echo
echo "AntennaMaster is up:  http://localhost:3000  (API docs: http://localhost:8000/docs)"
echo "Stop with: kill $BACK_PID $FRONT_PID"
wait
