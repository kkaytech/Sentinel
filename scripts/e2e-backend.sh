#!/bin/sh
# Backend for the end-to-end tests: a clean `sentinel_e2e` database, reference data, then the API.
# Started by Playwright (frontend/playwright.config.ts). Needs a PostgreSQL superuser
# (PGHOST, PGPORT, PGUSER, PGPASSWORD; default localhost:5432 as the current OS user).
set -e
cd "$(dirname "$0")/.."
PYTHON="${SENTINEL_PYTHON:-backend/.venv/bin/python}"
export SENTINEL_PYTHON="$PYTHON"
DATA=frontend/e2e/.data
"$PYTHON" scripts/dev_setup.py --database sentinel_e2e --reset
rm -rf "$DATA"
"$PYTHON" scripts/generate_reference_data.py --scale demo --dataset corrected --period 2026-09 --out "$DATA/2026-09" > /dev/null
"$PYTHON" scripts/generate_reference_data.py --scale demo --dataset defective --period 2026-10 --out "$DATA/2026-10" > /dev/null
ENV_FILE=.env.e2e PORT="${E2E_API_PORT:-8100}" exec sh scripts/dev-backend.sh
