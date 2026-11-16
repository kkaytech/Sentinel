# Sentinel

A pre-publication data quality gate for supplier invoice reporting:
*"Can we publish this dataset, and what evidence supports that decision?"*

**Status:** M1 step 1 (walking skeleton) — authentication, sessions, audit trail, database
privilege model and health check. See [CLAUDE.md](CLAUDE.md) and [docs/](docs/).

## Run with Docker

```bash
cp .env.example .env   # then replace every value
docker compose up --build
```

Create the first administrator (the password is prompted for, never passed as an argument):

```bash
docker compose run --rm app python -m sentinel.identity.cli create-user \
  --username admin --display-name "Administrator" --role ADMIN
```

The API listens on `http://127.0.0.1:8000` (`/health`, `/docs`).

## Develop and test

Tests need PostgreSQL 16+ reachable as a superuser through `SENTINEL_TEST_ADMIN_URL`. The suite
creates the Sentinel roles and a throwaway `sentinel_test` database itself.

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
SENTINEL_TEST_ADMIN_URL=postgresql+psycopg://postgres:postgres@localhost:5432/postgres .venv/bin/pytest
.venv/bin/ruff check src migrations tests && .venv/bin/mypy && .venv/bin/lint-imports
```
