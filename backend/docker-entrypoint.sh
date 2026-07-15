#!/bin/sh
# Start the FastAPI backend, honoring UVICORN_WORKERS (default 2).
set -e
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers "${UVICORN_WORKERS:-2}"
