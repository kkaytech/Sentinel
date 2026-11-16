#!/usr/bin/env bash
# Docker entrypoint init script for the `db` service (runs once, on an empty data volume).
# Creates the three Sentinel roles and the `sentinel` database owned by sentinel_owner.
set -euo pipefail

: "${SENTINEL_OWNER_PASSWORD:?required}"
: "${SENTINEL_APP_PASSWORD:?required}"
: "${SENTINEL_READER_PASSWORD:?required}"

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres \
    -v owner_password="$SENTINEL_OWNER_PASSWORD" \
    -v app_password="$SENTINEL_APP_PASSWORD" \
    -v reader_password="$SENTINEL_READER_PASSWORD" \
    -f /sentinel-init/create_roles.sql

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres \
    -c "CREATE DATABASE sentinel OWNER sentinel_owner ENCODING 'UTF8' TEMPLATE template0;"
