#!/bin/sh
# Run the browser journey against the Docker Compose stack, on a fresh database volume.
#   sh scripts/e2e-docker.sh
# Needs Docker, Node and the backend virtualenv (only to generate the reference data).
# WARNING: removes the stack's data volume first, so it must not hold anything you need.
set -e
cd "$(dirname "$0")/.."
[ -f .env ] || { echo "Create .env first (cp .env.example .env and set the values)." >&2; exit 1; }
PASSWORD="$(python3 -c 'import secrets; print(secrets.token_urlsafe(18))')"
docker compose down --volumes
docker compose up --build --detach
for attempt in $(seq 1 60); do
  curl --fail --silent http://127.0.0.1:8000/health > /dev/null && break
  sleep 2
done
for user in "admin Demo_Administrator ADMIN" "analyst Demo_Analyst ANALYST" "approver Demo_Approver APPROVER"; do
  set -- $user
  docker compose exec -T -e SENTINEL_NEW_USER_PASSWORD="$PASSWORD" app \
    python -m sentinel.identity.cli create-user --username "$1" \
    --display-name "$(echo "$2" | tr _ ' ')" --role "$3"
done
sh scripts/e2e-data.sh
cd frontend
E2E_EXTERNAL=1 E2E_BASE_URL=http://127.0.0.1:8000 E2E_PASSWORD="$PASSWORD" npx playwright test
