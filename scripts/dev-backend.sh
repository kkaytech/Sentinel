#!/bin/sh
# Start the API for local development on http://127.0.0.1:8000 (run scripts/dev_setup.py first).
set -e
cd "$(dirname "$0")/.."
if [ ! -f .env.dev ]; then
  echo "Run: backend/.venv/bin/python scripts/dev_setup.py" >&2
  exit 1
fi
set -a
. ./.env.dev
set +a
exec backend/.venv/bin/uvicorn sentinel.api.app:create_app --factory --host 127.0.0.1 --port 8000
