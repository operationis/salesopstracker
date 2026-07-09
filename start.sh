#!/usr/bin/env bash
# Production start (Linux) — gunicorn, single worker, thread-scaled.
set -e
cd "$(dirname "$0")"
export PORT="${PORT:-5004}"
export PORTAL_BASE_URL="${PORTAL_BASE_URL:-http://localhost:5004}"
exec gunicorn -w 1 -k gthread --threads 8 --timeout 120 -b "0.0.0.0:${PORT}" wsgi:application
