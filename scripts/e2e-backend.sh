#!/bin/sh
# Backend for the end-to-end tests: a clean `sentinel_e2e` database, reference data, then the API.
# Started by Playwright (frontend/playwright.config.ts). Needs a PostgreSQL superuser
# (PGHOST, PGPORT, PGUSER, PGPASSWORD; default localhost:5432 as the current OS user).
set -e
cd "$(dirname "$0")/.."
PYTHON="${SENTINEL_PYTHON:-backend/.venv/bin/python}"
export SENTINEL_PYTHON="$PYTHON"
"$PYTHON" scripts/dev_setup.py --database sentinel_e2e --reset
sh scripts/e2e-data.sh
ENV_FILE=.env.e2e PORT="${E2E_API_PORT:-8100}" exec sh scripts/dev-backend.sh
