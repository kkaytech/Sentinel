#!/bin/sh
# Regenerate the demo datasets in demo-data/. Each period's invoices are dated inside that
# period, so validation results and KPIs read sensibly. Deterministic: same output every run.
set -e
cd "$(dirname "$0")/.."
PYTHON="${SENTINEL_PYTHON:-backend/.venv/bin/python}"
make() {  # period dataset seed
  "$PYTHON" scripts/generate_reference_data.py --scale demo --dataset "$2" --period "$1" \
    --seed "$3" --out "demo-data/$1" > /dev/null
  rm -f "demo-data/$1/catalogue.json"
}
make 2026-09 corrected 20260915
make 2026-10 defective 20261015
make 2026-11 clean 20261115
echo "demo-data/ regenerated"
