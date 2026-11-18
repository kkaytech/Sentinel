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

**Priority (product owner, 2026-11-16): get a working, usable browser application.** Build features, frontend first, wired to the real backend. No fake or hardcoded data. No AI work (M2) until the core journey works. Do not spend effort on documentation beyond what the app needs.

**Target journey:** sign in → upload CSVs → view dataset → run validation → inspect findings → view impact → resolve issues (waivers) → review and approve → publish.

| Area | State |
|---|---|
| Auth, sessions, CSRF, users, audit, `/health` (migrations 0001–0003) | Implemented, tested |
| Config versions and reload (0004) | Implemented, tested |
| Ingestion, versions, raw files (0005) | Implemented, tested |
| Rule engine: 12 rule types, 32 rules (0006) | Implemented, tested against the generator's catalogue |
| Impact figures, totals, KPI-01..04 (0007) | Implemented, tested |
| Issues, notes, waivers, review, approval, staleness (0008) | Implemented, tested. Staleness runs through `shared/hooks.py`, registered in `api/app.py`. |
| Publication: eligibility E1–E7, snapshot, manifest, export ZIP, verify, offline verifier (0009) | Implemented, tested |
| Frontend (`frontend/`): sign in, periods, upload, version, findings, finding and issue, impact, review and publish, publications, audit, users | Implemented. Covered by Playwright (`frontend/e2e/`): the full journey plus a no-horizontal-overflow check at phone, tablet and desktop widths. |
| Validation run execution | **Partial:** runs inside the `POST /versions/{id}/runs` request (202 with the final status). No job queue or crash recovery yet (`app.jobs` is not created). |
| Finding drill-down | **Partial:** `failing_columns` lists the rule's columns, not the failing cells. |
| Config reload response | **Partial:** `stale_counts` is always zero, although staleness is propagated. |
| Single application | Implemented: the API serves `frontend/dist` with an index.html fallback (`api/frontend.py`); `sh scripts/run.sh` builds and starts it on :8000. The Dockerfile builds the UI in a node stage. |
| PRD §18.2 negative matrix as one suite, `scripts/benchmark.py` | Not started (most negative cases are covered across `tests/api/`) |
| Column profiling FR-005 (M3), `published.*_current` views (M3), AI explanations (M2) | Not started |
| Docker Compose and CI | Compose **verified locally on Docker Desktop (2026-11-18)**: image build, PostgreSQL 16 init, migrations, app health, and the full Playwright journey (`sh scripts/e2e-docker.sh`). **CI never executed** (the repo has no remote); its Docker job runs the same script. |

**Outstanding, do not lose:**
- **ARD TQ-07:** re-run PoC-1 in the reference environment (`postgres:16`, Docker, 4 vCPU). It was measured on PostgreSQL 18.4 natively.
- A finding over the 10,000 key cap keeps an exact count, but its impact covers only the stored keys (`inputs.key_list_truncated`). Needs a product decision.
- The Bash tool can stall after a test run finishes. Redirect pytest output to a log file and grep it.

**Engine rules to keep (decided after PoC-1):**
- The completion transaction applies `RUN_SETTINGS` in `validation/service.py`: `SET LOCAL work_mem = '64MB'`, `jit = off` and `enable_nestloop = off`. Do not remove the last two: on `postgres:16` (which has LLVM) JIT compilation made runs take 105–214 s instead of about 12 s, and right after a large upload stale statistics led to a 563 s run. Homebrew PostgreSQL has no LLVM, so local runs never show the JIT problem.
- Each table's primary-key `unique` rule is evaluated first; findings are stored and shown in rule-ID order.
- Currency columns in impact tables are `text`. An invalid currency is a finding, never an insert failure.
- In SQLAlchemy Core, group or order by a subquery column, never by a repeated expression: each repeat gets its own bind parameter and PostgreSQL then rejects the `GROUP BY`.

**Run the app locally** (from the repo root):
- Once: `backend/.venv/bin/python scripts/dev_setup.py`. It creates the roles and the `sentinel_dev` database on local PostgreSQL (default `localhost:5432` as the OS user; override with `PGHOST`/`PGPORT`/`PGUSER`), migrates, and creates the demo users `admin`, `analyst` and `approver`. Secrets go to the git-ignored `.env.dev`; the demo password is in the git-ignored `.demo-credentials`. Re-run it after adding a migration.
- API: `sh scripts/dev-backend.sh` (http://127.0.0.1:8000).
- Web: `npm --prefix frontend run dev` (http://localhost:5173, proxies `/api` to the API). Type-check with `npm --prefix frontend run typecheck`.
- One application, no hot reload: `sh scripts/run.sh` (add `--build` after UI changes).
- End-to-end tests: `npm --prefix frontend run e2e`. They reset a `sentinel_e2e` database on the dev cluster, generate reference data and start their own servers. `E2E_BASE_URL=http://127.0.0.1:8100` runs them against the built bundle instead of Vite.
- Demo data: committed in `demo-data/<period>/` (regenerate with `sh scripts/make_demo_data.sh`). Always generate data with `--period` equal to the period it is uploaded under.
- Never point the test suite at the dev cluster: it resets the `sentinel_*` role passwords. Use a separate throwaway cluster for `SENTINEL_TEST_ADMIN_URL`.

**Frontend conventions:** React + TypeScript + Vite, no UI library. `src/api.ts` is the only place that calls the API and holds the response types (hand-written; the API returns untyped dicts, so OpenAPI generation gives nothing useful yet). The browser computes no eligibility and no impact. Severity, state and category are always text labels.

**Commands** (run from `backend/`):
- Tests: `SENTINEL_TEST_ADMIN_URL=postgresql+psycopg://<superuser>@<host>:<port>/postgres .venv/bin/pytest --cov`. The suite creates the roles and a throwaway `sentinel_test` database itself.
- Gate: `.venv/bin/ruff check src migrations tests && .venv/bin/ruff format --check src migrations tests && .venv/bin/mypy && .venv/bin/lint-imports`
- Migrations: `SENTINEL_OWNER_DATABASE_URL=… .venv/bin/alembic upgrade head`. This runs as `sentinel_owner` only; `env.py` refuses any other role.
- First admin: `.venv/bin/python -m sentinel.identity.cli create-user --username admin --display-name "Admin" --role ADMIN`. The password comes from `SENTINEL_NEW_USER_PASSWORD` or a prompt.
- Docker: `cp .env.example .env && docker compose up --build`. Not yet verified, because Docker isn't installed on the dev machine; CI is the first real check.

**Gotchas:**
- FastAPI ≥ 0.16x wraps included routers lazily, so `app.routes` holds no `APIRoute`s. Route-level tests must read `app.openapi()` instead.
- A local test cluster on macOS needs `LC_ALL=C`.
