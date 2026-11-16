# Sentinel — project instructions

Sentinel is a pre-publication data quality gate for monthly supplier invoice CSVs. It answers one question: "Can we publish this dataset, and what evidence supports that decision?" It is a solo portfolio project, so keep breadth narrow and depth real.

## Source of truth (read before changing behaviour)

| Doc | Use for |
|---|---|
| `docs/01-product-requirements.md` (PRD v1.1, approved) | Scope, requirement IDs (FR/NFR/BR/AI/PUB), acceptance criteria |
| `docs/02-architecture-review.md` (ARD v1.2, approved) | Decisions ADR-001…018, modules, DB roles, canonical formats, PoC-1 |
| `docs/03-functional-specification.md` | State machines, rule catalogue, impact/KPI formulas, eligibility algorithm, error codes, screens |
| `docs/04-api-and-data-specification.md` | Endpoints, tables, guards, config formats, manifest, M1 build order |
| `requirements/sentinel original brief.md` | Original brief. Keep the filename (with spaces) as is; never rename, copy or edit it. |

- **Scope.** Do not add capabilities beyond the PRD MVP. If a change would alter a requirement or an ADR, propose a change request and wait for approval.
- **Provisional data.** The dataset contract (PRD §12.2) and the KPIs (PRD §12.3) are provisional until the product owner reviews them.

## Approval boundaries (never cross without explicit approval)

- No live AI provider calls. Tests, CI and local development use the stub provider only, with `SENTINEL_AI_ENABLED=false` and no `ANTHROPIC_API_KEY`.
- No AI evaluation spend (about $8–$27 for Stage 1).
- The provider's data terms must be reviewed before any live AI use.
- Do not commit, push or open PRs unless asked.

## Architecture invariants (non-negotiable)

1. **AI is advisory only.** Nothing in `validation`, `impact`, `review` or `publication` imports `ai_explanation`. `ai_explanation` never imports `review` or `publication`. Only `api` imports `ai_explanation`. import-linter enforces this in CI.
2. **One eligibility function.** `publication.evaluate_eligibility` (checks E1–E7) serves both the dry run and publish. Only the publication service writes to `published.*`. Publish runs in one transaction that takes the period lock (`NOWAIT`).
3. **Decisions bind to a tuple.** Waivers, review requests and approvals store (`dataset_version_id`, `content_hash`, `validation_run_id`, `rule_set_version_id`). The gate recomputes staleness itself and never trusts a stored `STALE` flag.
4. **History is immutable.**
   - The app connects as `sentinel_app`. It owns nothing and has insert-only grants on history plus column-limited `UPDATE` on state fields.
   - `sentinel_owner` is used only by migrations and never reaches the app container.
   - Keep the triggers working: forbid-change, seal-on-commit, open-parent, segregation of duties and the publication backstop (Doc 4 §4.10).
   - New tables need grants that match ARD §7.3.2. The grant-drift test must pass.
5. **Money and determinism.**
   - Use `NUMERIC(18,2)` and Python `Decimal`. Never floats.
   - Rule SQL contains no `now()`, `CURRENT_DATE` or randomness. It uses the run's reference date.
   - Every query has an `ORDER BY` on a stable key.
6. **Canonical formats are versioned.** `SENTINEL-CONTENT-V1`, `SENTINEL-SNAPSHOT-V1` and `SENTINEL-MANIFEST-V1` (ARD §8.3). Never change them silently. Golden-file tests guard them. Store the manifest as exact bytes, never as JSONB.
7. **Fail closed.**
   - An engine error makes the run `ERROR`.
   - Crash recovery marks `RUNNING` jobs `FAILED`.
   - An audit insert failure rolls back the action.
   - There are no automatic retries.
8. **Impact wording.** Impact is "confirmed discrepancy", "potential exposure" or "estimated reporting impact". Never use the word "loss".
9. **Segregation of duties is by user ID.** The approver must differ from the submitter, and the waiver decider from the requester. Self-approval is never allowed, even in the demo.

## Security rules

- **Authorisation.** Every service command calls `sentinel.shared.authz.require(principal, Permission.X)` first. Route checks are not enough on their own. Every route uses `protected(...)` or `public()` from `sentinel.api.deps`, and every state-changing route is listed in `sentinel/api/audit_map.py`. Tests enforce both.
- **Layering.** The import-linter layers are `api → publication → review → impact → validation → ingestion → config → identity → audit → shared` (ARD §6.2, CR-06 approved). The permission policy lives in `shared.authz`.
- **SQL.** Bound parameters only. Validate column names against the contract and pass them as JSONB key parameters. Never use string-built SQL.
- **Secrets.** Secrets come from the environment only. `.env.example` holds placeholders. gitleaks must pass.
- **Logs and audit payloads** never contain data cell values, passwords, tokens or keys.
- **CSV exports** for viewing neutralise formula-leading cells. The verification ZIP is byte-exact by design.

## Code layout and conventions

- **Backend:** `backend/src/sentinel/{shared,identity,audit,config,ingestion,validation,impact,review,publication,ai_explanation,jobs,api}`, with Alembic migrations in `backend/migrations/`.
- **Frontend:** React, TypeScript and Vite in `frontend/`. It computes no eligibility or impact. API types are generated from OpenAPI.
- **Configuration:** `config/datasets/supplier_invoices/{contract,rules}.yaml`.
- **Reference data:** `scripts/generate_reference_data.py`; tests load it through `backend/tests/reference.py`.
- **Endpoints:** synchronous FastAPI. One unit of work per command, committed once, with `audit.record` in the same transaction.
- **Traceability:** reference requirement IDs in test names or docstrings, for example `test_fr_004_3_version_rows_immutable`.

## Testing (required for every change)

- **Test pyramid.**
  - Unit: pytest and Hypothesis.
  - Integration and API: real PostgreSQL 16. Migrations run as owner, and tests connect as `sentinel_app`.
  - End to end: API-level tests plus a Playwright smoke test.
- **Coverage.** At least 85% on validation, impact, publication and audit; at least 70% across the backend.
- **Always green.** The permission matrix, audit coverage, grant drift, the PRD §18.2 negative matrix and import-linter.
- **Oracle.** The defect catalogue from `scripts/generate_reference_data.py` is the test oracle. Expected values come from it, not from the code under test.

## Current status and next step

**M1 steps 1–3 are done.**
- Step 1: walking skeleton (migrations 0001–0003, authentication, sessions, CSRF, throttling, users, audit, `/health`).
- Step 2: PoC-1. Variant A adopted; ADR-006 is Accepted (ARD v1.2 §10.1.1, `docs/poc-01-validation-performance.md`).
- Step 3: configuration loading, ingestion and versions, the rule engine (all 12 rule types, 32 rules) and impact (migrations 0004–0007; Doc 4 §3.2–§3.5).

**Next is step 4:** issues, waivers, review and staleness (migration 0008).

**Outstanding, do not lose:**
- **ARD TQ-07:** re-run PoC-1 in the reference environment (`postgres:16`, Docker, 4 vCPU). It was measured on PostgreSQL 18.4 natively.
- Validation runs execute inside the `POST /versions/{id}/runs` request until the job queue arrives with migration 0009 (step 5). The response is `202` with the run already in its final status.
- `scripts/benchmark.py` (NFR-001.1) is not built yet.
- Column profiling (FR-005) is M3; `app.column_profiles` exists but is not populated.
- The project is not yet a Git repository; initialise it before the first commit.

**Engine rules to keep (decided after PoC-1):**
- The completion transaction starts with `SET LOCAL work_mem = '64MB'`.
- Each table's primary-key `unique` rule is evaluated first; findings are stored and shown in rule-ID order.
- Currency columns in impact tables are `text`. An invalid currency is a finding, never an insert failure.
- In SQLAlchemy Core, group or order by a subquery column, never by a repeated expression: each repeat gets its own bind parameter and PostgreSQL then rejects the `GROUP BY`.

**Commands** (run from `backend/`):
- Tests: `SENTINEL_TEST_ADMIN_URL=postgresql+psycopg://<superuser>@<host>:<port>/postgres .venv/bin/pytest --cov`. The suite creates the roles and a throwaway `sentinel_test` database itself.
- Gate: `.venv/bin/ruff check src migrations tests && .venv/bin/ruff format --check src migrations tests && .venv/bin/mypy && .venv/bin/lint-imports`
- Migrations: `SENTINEL_OWNER_DATABASE_URL=… .venv/bin/alembic upgrade head`. This runs as `sentinel_owner` only; `env.py` refuses any other role.
- First admin: `.venv/bin/python -m sentinel.identity.cli create-user --username admin --display-name "Admin" --role ADMIN`. The password comes from `SENTINEL_NEW_USER_PASSWORD` or a prompt.
- Docker: `cp .env.example .env && docker compose up --build`. Not yet verified, because Docker isn't installed on the dev machine; CI is the first real check.

**Gotchas:**
- FastAPI ≥ 0.16x wraps included routers lazily, so `app.routes` holds no `APIRoute`s. Route-level tests must read `app.openapi()` instead.
- A local test cluster on macOS needs `LC_ALL=C`.
