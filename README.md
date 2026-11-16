# Sentinel

A pre-publication data quality gate for supplier invoice reporting. It answers one question:
*"Can we publish this dataset, and what evidence supports that decision?"*

Upload a month of supplier and invoice CSVs. Sentinel validates them with deterministic rules,
quantifies the financial and reporting impact of each problem, routes blocking issues through
waivers and a second-person approval, and only then publishes an immutable, hash-verified
snapshot with a manifest of the evidence.

## What it demonstrates

- **Data engineering:** 32 configurable validation rules of 12 types, compiled to parameterised
  SQL and run inside PostgreSQL over raw JSONB rows (100,000 invoices validate in about 6 s).
- **Exact financial impact:** confirmed discrepancies, potential exposure and KPI deltas per
  currency, in decimal arithmetic, checked against a generated defect catalogue.
- **Governance enforced by the backend and the database:** segregation of duties by user ID,
  decisions bound to the exact data and validation they were made for, an append-only audit
  trail, and a least-privilege database role that cannot alter history.
- **Verifiable publication:** one eligibility check serves both the dry run and publish; the
  export ZIP verifies offline with a standard-library script.
- **Full stack:** FastAPI, SQLAlchemy Core, PostgreSQL, React and TypeScript, with pytest and
  Playwright end-to-end tests.

## Run it locally

Needs PostgreSQL 16 or later, Python 3.12 or later and Node 20 or later.

```bash
python3 -m venv backend/.venv && backend/.venv/bin/pip install -e "backend[dev]"
backend/.venv/bin/python scripts/dev_setup.py   # database, roles, demo users (run once)
sh scripts/run.sh                               # builds the UI and starts http://127.0.0.1:8000
```

`dev_setup.py` connects to local PostgreSQL as your OS user (override with `PGHOST`, `PGPORT`,
`PGUSER`, `PGPASSWORD`). It creates three demo users, `analyst`, `approver` and `admin`, and
writes their shared password to `.demo-credentials`.

### A five-minute demo

Sample files are in [`demo-data/`](demo-data/README.md).

1. Sign in as `analyst`. Upload `demo-data/2026-10` for period 2026-10 and run validation.
   Explore the findings, the record drill-down and the reporting impact. This version has
   defects that cannot be waived, so the publication checklist refuses it.
2. Upload `demo-data/2026-09` for 2026-09 and run validation. Open `INV_FK_SUPPLIER` and
   request a waiver.
3. In a second browser profile, sign in as `approver` and grant the waiver.
4. As `analyst`, open **Review and publish** and submit for review.
5. As `approver`, acknowledge the warnings and approve. Either user can now publish.
6. Open the publication, click **Verify**, and download the export ZIP. Check it offline:
   `python scripts/verify_publication.py PUB-SUPINV-2026-09-001.zip`.

## Run with Docker

```bash
cp .env.example .env   # then replace every value
docker compose up --build
docker compose run --rm app python -m sentinel.identity.cli create-user \
  --username admin --display-name "Administrator" --role ADMIN
```

The application is at `http://127.0.0.1:8000`. Create the analyst and approver on the Users
screen.

## Develop and test

```bash
sh scripts/dev-backend.sh            # API on :8000
npm --prefix frontend run dev        # UI with hot reload on :5173

cd backend
SENTINEL_TEST_ADMIN_URL=postgresql+psycopg://<superuser>@<host>:<port>/postgres .venv/bin/pytest --cov
.venv/bin/ruff check src migrations tests && .venv/bin/mypy && .venv/bin/lint-imports

cd ../frontend
npx playwright install chromium      # once
npm run e2e                          # the whole journey in a real browser, real API and database
```

Use a throwaway PostgreSQL cluster for `pytest`: the suite resets the Sentinel role passwords.
Design documents are in [`docs/`](docs/); working conventions are in [`CLAUDE.md`](CLAUDE.md).
