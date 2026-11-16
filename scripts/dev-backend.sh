#!/bin/sh
# Start the API for local development (run scripts/dev_setup.py first).
#   ENV_FILE  settings file, default .env.dev
#   PORT      default 8000
set -e
cd "$(dirname "$0")/.."
ENV_FILE="${ENV_FILE:-.env.dev}"
if [ ! -f "$ENV_FILE" ]; then
  echo "Run: backend/.venv/bin/python scripts/dev_setup.py" >&2
  exit 1
fi
set -a
. "./$ENV_FILE"
set +a
PYTHON="${SENTINEL_PYTHON:-backend/.venv/bin/python}"
exec "$PYTHON" -m uvicorn sentinel.api.app:create_app --factory --host 127.0.0.1 --port "${PORT:-8000}"
