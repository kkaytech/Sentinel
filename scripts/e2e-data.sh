#!/bin/sh
# Reference data for the end-to-end tests, written to frontend/e2e/.data.
set -e
cd "$(dirname "$0")/.."
PYTHON="${SENTINEL_PYTHON:-backend/.venv/bin/python}"
DATA=frontend/e2e/.data
rm -rf "$DATA"
"$PYTHON" scripts/generate_reference_data.py --scale demo --dataset corrected --period 2026-09 --out "$DATA/2026-09" > /dev/null
"$PYTHON" scripts/generate_reference_data.py --scale demo --dataset defective --period 2026-10 --out "$DATA/2026-10" > /dev/null
