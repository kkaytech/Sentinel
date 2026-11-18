# Sentinel — PoC-1: Validation Performance

| Field | Value |
|---|---|
| Document | PoC-1 report (ARD §10.1 deliverable) |
| Date | 2026-11-15 |
| Status | Measured locally. **Evaluated and approved by the product owner on 2026-11-15:** variant A adopted and all four decisions below accepted (ARD v1.2 §10.1.1). PostgreSQL 16 reference run done on 2026-11-18 (below); it found and fixed two engine defects. |
| Scripts, plans, raw results | [`poc/01-validation/`](../poc/01-validation/) · generator: [`scripts/generate_reference_data.py`](../scripts/generate_reference_data.py) |

## Result

**Variant A (JSONB `version_rows`, primary key index only) passes.** Variants B and C were not needed and were not built.

| Pass criterion (ARD §10.1) | Limit | Measured (median / max of 5) | Result |
|---|---|---|---|
| 1. Full validation run, W1–W9 | ≤ 60 s, target ≤ 30 s | 3.04 s / 3.58 s | Pass |
| 2. Slowest single workload (W9) | ≤ 10 s median | 0.65 s | Pass |
| 3a. W10 ingestion with content hash | ≤ 60 s | 3.70 s / 3.83 s | Pass |
| 3b. W11 snapshot plus canonical CSV hash | ≤ 30 s | 3.64 s / 3.71 s | Pass |
| 4. No sort or hash spills to disk | At defaults, or a named setting change | **4 sorts spill at the default `work_mem` of 4 MB.** None spill with `SET LOCAL work_mem = '64MB'`. | Pass only with the setting change |
| 5. Findings match the catalogue | 100% | Exact match in every run | Pass |

All 16 rules run together (W1–W9 plus primary-key uniqueness and the four rules for D-03, D-07, D-09 and D-11) take 3.49 s median, 4.04 s maximum.

## PostgreSQL 16 reference run (2026-11-18, ARD TQ-07)

Measured on the stock `postgres:16` image (16.16, default settings) in Docker Desktop, limited
to 4 CPUs. **Difference from the reference environment:** Docker Desktop's VM had 4 GB of
memory, not 8 GB. At default settings PostgreSQL uses 128 MB of shared buffers and no swapping
was observed, so this is unlikely to matter, but it is not the specified environment.

| Workload (100,000 invoices) | Limit | Measured | Result |
|---|---|---|---|
| W1–W9, engine settings (`work_mem` 64 MB, `jit` off, `enable_nestloop` off) | ≤ 60 s, target ≤ 30 s | 4.2 s median, 6.5 s max | Pass |
| W1–W9, stock defaults | — | 8.6 s median; 4 sorts spill | For comparison |
| Slowest single workload (W9) | ≤ 10 s median | 1.0 s | Pass |
| W11 publish snapshot and hash | ≤ 30 s | 6.7 s median, 10.7 s max | Pass |
| W10 harness ingestion, rows streamed from the Mac through Docker's port forward | ≤ 60 s | 19.4 s median; **one run of 110 s** | See below |
| Real app: upload, then validate immediately, six new periods | ≤ 60 s (NFR-001) | upload 10.9–20.4 s, validation and impact 9.4–15.8 s; worst pair 35 s | Pass |
| Catalogue match | 100% | Exact | Pass |

**Two defects found and fixed.** Neither showed natively because Homebrew PostgreSQL has no
LLVM, and the native harness ran `ANALYZE` after loading.
1. **JIT compilation.** `postgres:16` JIT-compiles each expensive rule query, which cost
   several seconds per query (one KPI query: 3.6 s to run, 5.6 s to compile). Whole runs took
   105–214 s. The engine now sets `jit = off` in the validation transaction.
2. **Stale statistics after a large upload.** The first run after two 100,000-row uploads
   took 563 s, one cross-table query alone running for over 7 minutes. Run again once
   autovacuum had analysed the table, the same version took 17 s. The app role cannot run
   `ANALYZE`, so the engine now sets `enable_nestloop = off`, which keeps every rule on
   hash or merge joins. With both fixes, six uploads each validated straight away took
   9.4–15.8 s.

**Open observation.** Two ingestions out of eighteen in total took 103–110 s, in both cases
as the sixth consecutive 100,000-row load, while a WAL-triggered checkpoint was running. Disk
throughput in the VM was 942 MB/s, there was no swapping, and uploads are otherwise
CPU-bound in `COPY`. The six uploads after the fix did not reproduce it. Cause not
established.

Results: `poc/01-validation/results/*PG16*.json`; plans: `poc/01-validation/plans/PG16*`.

## Environment — differs from the reference environment

| | ARD §10.1 reference | What was actually used |
|---|---|---|
| PostgreSQL | `postgres:16` image | **18.4** (Homebrew) |
| Host | Docker Compose, 4 vCPU, 8 GB | **Native macOS, Apple M1, 8 cores, 8 GB**. Docker is not installed. |
| Settings | Defaults | Defaults from `initdb`: `shared_buffers` 128 MB, `work_mem` 4 MB, `max_parallel_workers_per_gather` 2, `jit` on |
| Database locale | `en_US.utf8` in the image | `C`. Every sort key in the rule SQL is `COLLATE "C"`, so this should not change sort cost. |

The margin is 10–20×, so the conclusion is unlikely to change, but **the run in the reference environment is still owed**. `poc.py` uses `pg_input_is_valid`, which needs PostgreSQL 16 or later, and nothing newer.

## Method

- **Data.** Seed 20261015, period 2026-10. 5,000 suppliers and 100,000 invoices with D-01 to D-12 planted at 50× the PRD §12.6 counts (5,100 planted defects plus 150 records carrying two defects). Regeneration is byte-identical.
- **Three versions loaded** (`defective`, `corrected`, `clean`; 313,520 rows), so every query filters by version inside a larger table.
- **Roles and guards.** The real migrations 0001–0003 plus PoC-local tables mirroring Doc 4 §4.5–§4.9. All work runs as `sentinel_app` with the seal-on-commit trigger active on `version_rows`, `raw_files` and `published.*`.
- **Rule SQL.** Bound parameters only, column names bound and checked against the contract, guarded casts, `NUMERIC(18,2)`, no clock functions, every result ordered.
- **Timing.** One warm-up and 5 measured runs. Each validation run is one transaction that writes `finding_records`, impact totals and KPI rows, then rolls back.
- **Oracle.** The catalogue records which rules each planted row must trip. Expected impact totals and KPI-02 values are computed in Python `Decimal`, independently of the SQL. The check compares row numbers, record keys, group membership, canonical records, impact totals per category and currency, and all 5,461 KPI-02 supplier/currency values.

## Timings

Seconds, median / maximum of 5 measured runs.

| # | Workload | Default `work_mem` (4 MB) | `SET LOCAL work_mem = '64MB'` |
|---|---|---|---|
| P0 | Primary-key uniqueness (feeds record keys) | 0.10 / 0.11 | 0.10 / 0.11 |
| W1 | Typed parse and sign range on amounts (3 rules) | 0.51 / 0.83 | 0.50 / 0.53 |
| W2 | Date validity and period window (2 rules) | 0.40 / 0.52 | 0.38 / 0.50 |
| W3 | Arithmetic check | 0.34 / 0.35 | 0.34 / 0.46 |
| W4 | Business-key uniqueness | 0.21 / 0.24 | 0.17 / 0.28 |
| W5 | Exact duplicate rows | 0.46 / 0.49 | 0.39 / 0.60 |
| W6 | Referential integrity | 0.05 / 0.07 | 0.06 / 0.10 |
| W7 | Supplier status and active window | 0.36 / 0.47 | 0.33 / 0.40 |
| X1 | Five remaining catalogue rules | 0.35 / 0.42 | 0.34 / 0.44 |
| W8 | Impact totals, de-duplicated, per currency | 0.02 / 0.03 | 0.02 / 0.03 |
| W9 | KPI-02 by supplier, as reported vs adjusted | 0.65 / 0.72 | 0.57 / 0.67 |
| | **W1–W9 full run** | **3.04 / 3.58** | **2.81 / 3.30** |
| | All 16 rules | 3.49 / 4.04 | 3.25 / 3.85 |
| W10 | Ingestion: parse and hash 0.75 s, insert and `COPY` 2.92 s | 3.70 / 3.83 | — |
| W11 | Publish: typed insert 2.93 s, ordered export and hash 0.73 s | 3.64 / 3.71 | — |

Other runs, each with an exact catalogue match:

| Run | W1–W9 |
|---|---|
| `clean` dataset (zero findings expected and found) | 2.74 s median |
| `corrected` dataset | 2.90 s median |
| After a server restart (shared buffers empty; the OS file cache could not be dropped) | 2.89 s, single run |
| Fresh load with no manual `ANALYZE`, 3 runs | 3.00 s median, 5.81 s maximum. Autoanalyze fired during this window, so not every run is certain to have been without statistics. |

**Storage.** One load-scale version (105,000 rows) takes 41.0 MB of table and 10.0 MB of primary key index, about 4× the 12.4 MB of CSV input.

## What the plans show

Plans are in `poc/01-validation/plans/`; `results/validate-*.json` holds a summary of each.

- **Access path.** Every rule reads the whole version once, by bitmap or index scan on the primary key, or by sequential scan. JSONB extraction and the guarded casts cost 0.1–0.35 s per pass over 100,000 rows. This is the dominant cost, and it grows linearly with the number of rules.
- **Disk spills at defaults.** Four sorts use `external merge`: W5 51 MB, W4 37 MB, W9 35 MB, P0 3 MB. With `work_mem` at 64 MB all four become in-memory quicksorts and no statement writes temp blocks.
- **Row estimates are poor.** There are no statistics on JSONB expressions, so estimates are off by up to 5,000×. The plans chosen are still reasonable at this size (hash joins to the 5,000 suppliers, a single sort per set rule).
- **Buffers.** Warm runs are served from shared buffers and the OS cache.
- **Seal guard cost.** In W11 the per-row seal trigger takes 1.9 s of the 3.3 s invoice insert (measured under `EXPLAIN ANALYZE`), and the foreign-key check 0.25 s. The same trigger runs for every `COPY` row in W10. It is the largest single cost in both, and both are far inside their limits.

## Assessment

- **ADR-005 (validation in PostgreSQL): confirmed** at load scale, subject to the reference-environment run.
- **ADR-006 (JSONB rows, variant A): suitable.** No expression indexes and no typed projection are needed, so `TEMPORARY` stays ungranted.
- **Extrapolation.** 16 rules take about 3.5 s. The full catalogue has 32, mostly single-pass rules of the same shape, so about 7–8 s is a reasonable expectation. That is an estimate, not a measurement.

## Decisions (all four approved 2026-11-15)

1. **Accept variant A** and move ADR-006 from Provisional to Accepted, closing TQ-04, either now or after the reference-environment run.
2. **`work_mem` for validation.** Recommended: the engine issues `SET LOCAL work_mem = '64MB'` inside the validation transaction. This is narrower than the Compose-wide change ARD §10.1 describes, so it needs approval as a small amendment.
3. **Primary-key rule runs first.** The record key falls back to `#<row_num>` when the key is duplicated (FS §4.1). Finding the duplicated keys once, through `INV_PK_UNIQUE`, and reusing that result is far cheaper than recomputing it per rule. FS §4.1 says evaluation order is ascending rule ID. Recommended clarification: the engine evaluates primary-key uniqueness first; findings are still stored and shown in rule-ID order.
4. **`currency char(3)` in `run_impact_totals` and `kpi_values`** (Doc 4 §4.7). Impact is grouped by the raw currency cell, so an invalid code longer than three characters would fail the insert and turn the run into `ERROR`. Recommended: `text`. The PoC tables use `text`.

## Not covered

- The reference environment (PostgreSQL 16 in Docker, 4 vCPU).
- A true cold cache.
- Half of the rule catalogue, the finding builder (samples, messages, key cap), issue creation and the open-parent guard.
- `INV_PK_UNIQUE` treats only duplicates as violations in the PoC; null keys are not planted or tested.
- `scripts/benchmark.py` (NFR-001.1) is not yet built from these scripts.

## Reproduce

```bash
cd poc/01-validation
P=../../backend/.venv/bin/python
for d in defective corrected clean; do $P ../../scripts/generate_reference_data.py --scale load --dataset $d --out out/load/$d; done
POC_PGPORT=55433 $P poc.py setup      # needs a superuser `sentinel_admin` and the three Sentinel roles
POC_PGPORT=55433 $P poc.py load
POC_PGPORT=55433 $P poc.py validate --label A
POC_PGPORT=55433 $P poc.py validate --label A-workmem64 --work-mem 64
POC_PGPORT=55433 $P poc.py publish --label A
```
