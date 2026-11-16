#!/bin/sh
# Run Sentinel as one application on http://127.0.0.1:8000: the API serving the built UI.
#   sh scripts/run.sh            build the UI if it has not been built, then start
#   sh scripts/run.sh --build    rebuild the UI first
# Needs scripts/dev_setup.py to have been run once. For UI development with hot reload use
# scripts/dev-backend.sh and `npm --prefix frontend run dev` instead.
set -e
cd "$(dirname "$0")/.."
if [ "$1" = "--build" ] || [ ! -f frontend/dist/index.html ]; then
  [ -d frontend/node_modules ] || npm --prefix frontend ci
  npm --prefix frontend run build
fi
echo "Sentinel: http://127.0.0.1:${PORT:-8000}  (sign-ins are in .demo-credentials)"
exec sh scripts/dev-backend.sh
