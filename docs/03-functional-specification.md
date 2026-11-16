# Sentinel — Functional Specification

| Field | Value |
|---|---|
| Document | 03 — Functional Specification |
| Version | 1.1 |
| Date | 2026-11-15 |
| Status | Issued for implementation (lean documentation phase) |
| Inputs | [PRD v1.1](01-product-requirements.md) · [Architecture Review v1.0](02-architecture-review.md) |
| Followed by | [04 — API & Data Specification](04-api-and-data-specification.md) |

**What this document does.** It turns the PRD into exact behaviour: state machines, the default rule catalogue, impact and KPI formulas, the eligibility algorithm, error codes and screens.

**What it does not do.** It adds **no capability** beyond the PRD's MVP. Where the PRD leaves a detail open, this document decides it and marks the decision **[FS-decision]**.

**What is still provisional.** The dataset contract (PRD §12.2) and the KPI definitions (PRD §12.3) are provisional pending the product owner's review (PRD OQ-01 and OQ-04; ARD TQ-05). Everything below that depends on them is provisional too. Changing them changes configuration and fixtures, not this document's structure.

---

## 1. Conventions

- **Identifiers.** Entities use UUIDs. Labels intended for people use fixed patterns:
  - dataset versions: `SUPINV-2026-10-v2`;
  - publications: `PUB-SUPINV-2026-10-001`.
- **Time.** Timestamps are UTC ISO-8601 with a `Z` suffix. The UI shows local time with the offset.
- **Money.** Amounts are decimal strings with 2 decimal places, always accompanied by the currency code (`"48200.00"` plus `"GBP"`).
- **"Current" state.**
  - The current version of a period is its latest version that is not superseded.
  - The current run of a version is defined by BR-003.
  - The current binding tuple is (current version, its content hash, current run, active rule set version).

---

## 2. State Machines

All transitions are performed by services. Every transition writes an audit event (FR-015). Any transition not listed here is rejected with `409 INVALID_TRANSITION`, and the response includes `allowed_transitions`.

### 2.1 Dataset version

The version's status is **stored** as `ACTIVE` or `SUPERSEDED`. The workflow state shown in the UI (FR-016) is **derived** from related records:

| Derived state | Condition (evaluated in order) |
|---|---|
| `SUPERSEDED` | `status = SUPERSEDED` |
| `PUBLISHED` | A publication exists for this version |
| `APPROVED` | An `APPROVED` review request exists, bound to the current tuple |
| `IN_REVIEW` | An `OPEN` review request exists |
| `VALIDATED` | The current run exists (BR-003) |
| `VALIDATION_FAILED` | The latest run is `ERROR` |
| `VALIDATING` | The latest run is `RUNNING` |
| `INGESTED` | Otherwise |

The dataset-period list (FR-016) shows the derived state of each period's current version. A period with no version shows `NO_DATA`.

### 2.2 Validation run

```
RUNNING ──(engine completes)──▶ COMPLETED
RUNNING ──(engine error / crash recovery)──▶ ERROR
```

- Terminal states never change.
- A new run on the same version is allowed whenever no run on that version is `RUNNING`. Starting one triggers staleness (§2.6).

### 2.3 Issue

| From | Event | To | Actor |
|---|---|---|---|
| — | Run `COMPLETED` with a `BLOCKING` or `WARNING` finding | `OPEN` | SYSTEM |
| `OPEN` | Waiver requested (`BLOCKING`, waivable rule only) | `WAIVER_REQUESTED` | ANALYST |
| `WAIVER_REQUESTED` | Waiver granted | `WAIVED` | APPROVER (not the requester) |
| `WAIVER_REQUESTED` | Waiver denied | `OPEN` | APPROVER (not the requester) |
| `OPEN`, `WAIVER_REQUESTED`, `WAIVED` | The run stops being current (§2.6) | `CLOSED_NOT_CURRENT` | SYSTEM |

- Notes can be added in any state.
- `WARNING` issues stay `OPEN` until they reach `CLOSED_NOT_CURRENT`. Approval acknowledges them (BR-006).

### 2.4 Waiver

| From | Event | To |
|---|---|---|
| — | Requested | `REQUESTED` |
| `REQUESTED` | Granted | `GRANTED` |
| `REQUESTED` | Denied | `DENIED` |
| `REQUESTED`, `GRANTED` | Binding tuple no longer current | `STALE` |

There is at most one `REQUESTED` or `GRANTED` waiver per issue. A new request after a `DENIED` decision is allowed.

### 2.5 Review request

| From | Event | To |
|---|---|---|
| — | Submitted | `OPEN` |
| `OPEN` | `APPROVE` | `APPROVED` |
| `OPEN` | `REJECT` | `REJECTED` |
| `OPEN`, `APPROVED` | Binding tuple no longer current | `STALE` |

There is at most one `OPEN` request per version (FR-014.2). After `REJECTED` or `STALE`, a new submission is allowed.

### 2.6 Staleness propagation (PUB-003)

Each trigger below runs in the **same transaction** as the event that causes it:

| Trigger | Effects |
|---|---|
| A new version is created for a period | Earlier versions → `SUPERSEDED`. Their issues → `CLOSED_NOT_CURRENT`. Their waivers and review requests (`REQUESTED`, `GRANTED`, `OPEN`, `APPROVED`) → `STALE`. |
| A new run is created for a version | The earlier runs' issues → `CLOSED_NOT_CURRENT`. Waivers and review requests bound to the earlier runs → `STALE`. |
| A new rule set version is activated | Issues of runs under the old rule set → `CLOSED_NOT_CURRENT`. Waivers and review requests bound to the old rule set → `STALE`. |

Each record that becomes `STALE` gets a `stale_reason` (`VERSION_SUPERSEDED`, `NEW_RUN` or `RULE_SET_CHANGED`) and one audit event.

**The eligibility check never relies on these stored statuses.** It recomputes the binding tuple every time (ARD ADR-013).

### 2.7 AI explanation (M2)

```
PENDING ──▶ VALID | FAILED_TIMEOUT | FAILED_PROVIDER | INVALID_OUTPUT | REJECTED_UNGROUNDED
(request with AI disabled) ──▶ DISABLED   (created terminal; no job)
```

The failure-reason values are defined in PRD AI-004 (v1.1). An explanation never changes the state of any other entity (AI-003).

### 2.8 Job

```
QUEUED ──(claimed)──▶ RUNNING ──▶ SUCCEEDED | FAILED
RUNNING at startup ──(recovery)──▶ FAILED
```

Failure is final; a failed job is never retried automatically.

---

## 3. Ingestion Behaviour (FR-003, FR-004, FR-005)

1. **Request.** A multipart upload with fields `period`, `suppliers` (file) and `invoices` (file).
2. **Pre-checks**, in order: the `period` format and range are valid (FR-003.7); both files are present; each file is within the size limit. The first failure stops the request with `422`, **no attempt record is created**, and an audit event `INGESTION_REJECTED` is still written. **[FS-decision]** Malformed requests do not produce attempt records.
3. **Structural parse.** This checks:
   - UTF-8 decoding, with a BOM accepted;
   - the header row;
   - duplicate header names, compared case-insensitively after trimming;
   - ragged rows;
   - unterminated quotes;
   - the row limit.

   Any failure creates an attempt record with status `FAILED` and an `errors[]` list (up to 100 entries of `{table, line, code}` plus `total`), and returns `422`. The codes are `ENCODING_ERROR`, `MISSING_HEADER`, `DUPLICATE_HEADER`, `RAGGED_ROW`, `UNTERMINATED_QUOTE` and `ROW_LIMIT_EXCEEDED`.
4. **Hash.** The content hash is computed with `SENTINEL-CONTENT-V1` (ARD §8.3.1).
   - If it equals the current version's hash: attempt `DUPLICATE_CONTENT`, `200`, and the existing version label is returned.
5. **Create.** In one transaction:
   - create the version;
   - store the rows and the raw files;
   - compute the profile (Should Have);
   - supersede earlier versions (§2.6);
   - record attempt `SUCCEEDED`;
   - return `201` with the version.
6. **Validation is not automatic.** The analyst triggers it. **[FS-decision]** This keeps each step visible in the demo.

**Header matching.**
- Contract columns match headers case-insensitively after trimming.
- Stored column names are the contract names.
- An unexpected header is stored under its trimmed original name and reported as an `INFO` finding.

---

## 4. Default Rule Catalogue (FR-002, FR-007, FR-008; PRD §12.5)

All rules below ship in `config/datasets/supplier_invoices/rules.yaml`. "NW" means non-waivable (BR-004). The `KPI` column lists the KPIs each rule declares it affects (PRD §12.3).

### 4.1 Semantics shared by all rule types

- **Null.** A value is null if it is absent, empty, or whitespace only.
- **Typed rules skip nulls.** `type_parse`, `range`, `column_comparison`, `arithmetic_check`, `date_window` and `allowed_values` evaluate non-null values only, and only those that parse. Unparseable values are reported by `type_parse` alone, so a single bad cell is never double-reported.
- **Record key.** The record key is the row's primary-key value. If that value is null or duplicated, the key falls back to `#<row_num>`. Findings always store the `row_num` as well.
- **Dependency.** If a rule references a missing required column, it records `NOT_EVALUATED` and creates no finding.
- **Determinism.**
  - **Presentation order.** Findings are stored and shown in ascending rule-ID order. Result order within a finding is ascending `row_num`, or the normalised key for set rules.
  - **Execution order.** The engine evaluates each table's primary-key `unique` rule first, because the record-key fallback above needs to know which key values are duplicated. The other rules follow in ascending rule-ID order. Execution order never changes what is stored or shown (ARD §8.4, clarified after PoC-1).

### 4.2 Catalogue

| Rule ID | Type | Target and parameters | Severity | NW | KPI | Defect (PRD §12.6) |
|---|---|---|---|:-:|---|---|
| `INV_SCHEMA_REQUIRED` | `required_column` | `invoices`, all required contract columns | BLOCKING | ✓ | all | — |
| `SUP_SCHEMA_REQUIRED` | `required_column` | `suppliers`, all required contract columns | BLOCKING | ✓ | all | — |
| `INV_SCHEMA_EXTRA` | `required_column` (extra-column mode) | `invoices` | INFO | — | — | — |
| `SUP_SCHEMA_EXTRA` | `required_column` (extra-column mode) | `suppliers` | INFO | — | — | — |
| `INV_TYPE_AMOUNTS` | `type_parse` | `net_amount`, `tax_amount`, `gross_amount` as `decimal(18,2)` | BLOCKING | ✓ | 01–04 | D-05 |
| `INV_TYPE_DATES` | `type_parse` | `invoice_date`, `due_date` as `date` | BLOCKING | ✓ | 01–04 | D-05 |
| `SUP_TYPE_DATES` | `type_parse` | `active_from`, `active_to` as `date` | BLOCKING | ✓ | — | — |
| `INV_PK_UNIQUE` | `unique` | `invoice_id`; null counts as a violation | BLOCKING | ✓ | 01–03 | D-01 (also) |
| `SUP_PK_UNIQUE` | `unique` | `supplier_id`; null counts as a violation | BLOCKING | ✓ | 02 | — |
| `INV_NN_GROSS` | `not_null` | `gross_amount` | BLOCKING | ✓ | 01–04 | — |
| `INV_NN_CURRENCY` | `not_null` | `currency` | BLOCKING | ✓ | 01–04 | — |
| `INV_NN_SUPPLIER` | `not_null` | `supplier_id` | BLOCKING | — | 02, 04 | D-03 |
| `INV_NN_OTHER` **[FS-decision]** | `not_null` | `supplier_invoice_number`, `document_type`, `invoice_date`, `due_date`, `net_amount`, `tax_amount`, `status` | BLOCKING | — | 01–03 | — |
| `SUP_NN_OTHER` **[FS-decision]** | `not_null` | `supplier_name`, `country_code`, `default_currency`, `status`, `active_from` | BLOCKING | — | 02 | — |
| `INV_DUP_ROWS` | `duplicate_rows` | All contract columns | BLOCKING | — | 01–03 | D-01 |
| `INV_BK_UNIQUE` | `unique` | (`supplier_id`, `upper(trim(supplier_invoice_number))`), non-null only | BLOCKING | — | 01–03 | D-02 |
| `INV_FK_SUPPLIER` | `foreign_key` | `invoices.supplier_id` → `suppliers.supplier_id` | BLOCKING | — | 02, 04 | D-04 |
| `INV_SIGN_INVOICE` | `range` | `gross_amount > 0` required where `document_type = 'INVOICE'` | BLOCKING | — | 01, 02 | D-06 |
| `INV_SIGN_CREDIT` | `range` | `gross_amount < 0` required where `document_type = 'CREDIT_NOTE'` | BLOCKING | — | 01, 02 | D-06 |
| `INV_ARITH` | `arithmetic_check` | `net_amount + tax_amount = gross_amount ± 0.01` | BLOCKING | — | 01, 02 | D-08 |
| `INV_DUE_BEFORE_INVOICE` | `column_comparison` | Flags `due_date < invoice_date` | WARNING | n/a | — | D-07 |
| `INV_CODE_CURRENCY` | `allowed_values` | `currency` ∈ the configured allowed list | WARNING | n/a | 01–04 | D-09 |
| `INV_CODE_STATUS` | `allowed_values` | `status` ∈ {RECEIVED, APPROVED, PAID, CANCELLED} | WARNING | n/a | 01–03 | D-09 |
| `INV_CODE_DOCTYPE` | `allowed_values` | `document_type` ∈ {INVOICE, CREDIT_NOTE} | WARNING | n/a | 01, 03 | — |
| `SUP_CODE_CURRENCY` | `allowed_values` | `default_currency` ∈ the allowed list | WARNING | n/a | — | — |
| `SUP_CODE_COUNTRY` | `allowed_values` | `country_code` ∈ ISO-3166 alpha-2 | WARNING | n/a | — | — |
| `SUP_CODE_STATUS` | `allowed_values` | `status` ∈ {ACTIVE, INACTIVE, BLOCKED} | WARNING | n/a | — | — |
| `SUP_ACTIVE_RANGE` **[FS-decision]** | `column_comparison` | Flags `active_to < active_from` | WARNING | n/a | — | — |
| `INV_SUPPLIER_STATUS` | `cross_table_condition` | Supplier `BLOCKED`; or `invoice_date` < `active_from`; or `invoice_date` > `active_to` | WARNING | n/a | 02 | D-10 |
| `INV_CURRENCY_MISMATCH` | `cross_table_condition` | `invoices.currency ≠ suppliers.default_currency` | WARNING | n/a | — | D-11 |
| `INV_OUT_OF_PERIOD` | `date_window` | `invoice_date` outside the run's reporting period | WARNING | n/a | 01–03 | D-12 |
| `INV_FUTURE_DATED` | `date_window` | `invoice_date` > the run's reference date | WARNING | n/a | 01–03 | — |

**Notes on the catalogue:**
- **Exact duplicates trip two rules.** Exact duplicate rows (D-01) share an `invoice_id`, so they are also reported by the non-waivable `INV_PK_UNIQUE`. As a result, D-01 can be fixed only at source. The *corrected* reference dataset fixes it (PRD §12.6). Impact is not double-counted (§5.3).
- **Why the [FS-decision] rules exist.**
  - The `*_NN_OTHER` rules cover required columns the PRD lists in §12.2 but does not name in §12.5. They are waivable, consistent with BR-004's non-waivable list being exhaustive.
  - `SUP_ACTIVE_RANGE` implements the §12.2 constraint `active_to ≥ active_from`.
  - Neither adds a capability. They configure FR-007 and FR-008.
- **Reference date.** It is the last day of the period plus 15 days (FR-006).

### 4.3 Message templates

Each rule has a fixed template, rendered from its counts. Examples:

- `INV_BK_UNIQUE`: "{groups} duplicate invoice groups ({records} records) share supplier and invoice number."
- `INV_FK_SUPPLIER`: "{records} invoices reference {suppliers} supplier IDs not present in suppliers.csv."

---

## 5. Impact Calculation (FR-011, FR-012; BR-007, BR-008)

### 5.1 Inputs

- **Amount.** `amount(r)` is the guarded `gross_amount` cast. It is null if the value does not parse.
- **Currency.** Figures are grouped by the raw `currency` cell, whatever it contains. An invalid code is reported by `INV_CODE_CURRENCY` and a null by `INV_NN_CURRENCY`; neither stops impact from being computed. A null currency is grouped under the empty string. The currency columns that store these groups are `text` (Doc 4 §4.7).
- **Exclusions.** A record counts toward KPIs only if `status ≠ 'CANCELLED'` and `invoice_date` falls within the period. Rows whose `invoice_date` does not parse are excluded from KPIs and counted under "value not quantifiable".

### 5.2 Per-rule impact mapping

| Rule | Category | Figure per currency |
|---|---|---|
| `INV_DUP_ROWS`, `INV_BK_UNIQUE` | **Confirmed discrepancy** | Σ `amount` over the **non-canonical** members (canonical = lowest `row_num`, BR-007) |
| `INV_ARITH` | **Confirmed discrepancy** | Σ \|`net + tax − gross`\| |
| `INV_PK_UNIQUE` | Potential exposure | Σ `amount` over the non-canonical members. These rows share an ID but may differ in content, so which one is correct is unknown. |
| `INV_NN_SUPPLIER`, `INV_FK_SUPPLIER` | Potential exposure | Σ `amount` (unattributable) |
| `INV_SUPPLIER_STATUS` | Potential exposure | Σ `amount` |
| `INV_SIGN_INVOICE`, `INV_SIGN_CREDIT` **[FS-decision]** | Potential exposure | Σ \|`amount`\|. The sign error is proven, but the correct document type or amount is not. |
| `INV_TYPE_AMOUNTS` | Potential exposure | Count only ("value not quantifiable") |
| All rules with KPI links | **Estimated reporting impact** | KPI deltas (§5.4) |
| Other rules | — | No monetary figure |

### 5.3 Version totals (overlap-aware)

1. Build the set **C** of record keys that contribute to any confirmed-discrepancy figure. The version's confirmed total per currency is Σ over C.
   - The arithmetic difference is added separately, per record.
   - **[FS-decision]** A record that is both a non-canonical duplicate and an arithmetic mismatch counts once, at its gross amount.
2. Build the set **P** of keys that contribute to any potential-exposure figure, **minus C**. The version's potential total is Σ `amount` over P, plus the "not quantifiable" count.
3. Per-issue figures are never de-duplicated across issues. Only version totals are.

### 5.4 KPIs and adjustments (PRD §12.3, provisional)

For an exclusion set X:
- `KPI01(X)` = Σ `amount` over included records not in X, per currency.
- `KPI02(X)` = `KPI01(X)` grouped by `supplier_id`, for records whose `supplier_id` is present in `suppliers`.
- `KPI03(X)` = the count of included `INVOICE` rows not in X.
- `KPI04(X)` = Σ `amount` over included records with a null or orphaned `supplier_id`, not in X.

| Adjustment for rule | X (excluded) | Assumption text shown |
|---|---|---|
| `INV_DUP_ROWS`, `INV_BK_UNIQUE` | The non-canonical members | "Duplicate copies removed; the first occurrence is kept by convention." |
| `INV_PK_UNIQUE` | The non-canonical members | "Rows sharing an invoice ID counted once (first occurrence)." |
| `INV_OUT_OF_PERIOD` | None. These rows are already excluded by the KPI period filter. The issue's figure is instead Σ `amount` of the out-of-period rows, labelled as the amount by which a report **without a period filter** would overstate KPI-01. | "A report without a period filter would include these invoices." |
| `INV_NN_SUPPLIER`, `INV_FK_SUPPLIER` | No exclusion for KPI-01, so its direction is `INDETERMINATE` for KPI-02 | "Spend is real but cannot be attributed to a supplier." |
| All others with KPI links | None. Direction `INDETERMINATE`. | "Correct treatment unknown." |

**Outputs:**
- **As reported:** X = ∅, using the KPI definitions above, period filter included. Because every value uses the same definition, the KPI-01 delta reflects only the excluded records, which FR-012.1 relies on.
- **Per-issue adjusted:** X = that issue's exclusion set.
- **Fully adjusted:** X = the union of all confirmed-discrepancy exclusion sets.

**Direction:** `OVERSTATED` if as-reported > adjusted, `UNDERSTATED` if lower, `INDETERMINATE` where the table says so. The delta is shown as an absolute value and as a percentage, rounded with ROUND_HALF_EVEN to 2 decimal places.

---

## 6. Waivers, Review and Approval (FR-013, FR-014; BR-004 to BR-006)

| Action | Preconditions (each failure gives the code shown) |
|---|---|
| Request waiver | The issue is `OPEN` (`INVALID_TRANSITION`); the issue is `BLOCKING` (`WAIVER_NOT_APPLICABLE`); the rule is waivable (`RULE_NOT_WAIVABLE`); a category is given and the justification is ≥ 30 characters (`422 VALIDATION_ERROR`); the issue's run is current (`STALE_REVIEW`) |
| Decide waiver | The caller is `APPROVER` and not the requester (`SEGREGATION_OF_DUTIES`); the waiver is `REQUESTED`; a comment is given for a denial (`422`); the tuple is current (`STALE_REVIEW`) |
| Submit review | The caller is `ANALYST`; the version is current (`VERSION_SUPERSEDED`); the current run is `COMPLETED` (`NO_CURRENT_VALIDATION`); no other request is `OPEN` (`REVIEW_ALREADY_OPEN`); a note is given (`422`) |
| Approve | The caller is `APPROVER` and not the submitter (`SEGREGATION_OF_DUTIES`); the request is `OPEN`; the tuple is current (`STALE_REVIEW`); `acknowledged_warning_count` equals the count of `OPEN` `WARNING` issues in the current run (`WARNING_COUNT_MISMATCH`) |
| Reject | As for approve, minus the warning count; a comment is given (`422`) |

**Approving with unwaived blockers. [FS-decision]** An approval may be recorded while `BLOCKING` issues are still unwaived. Publication eligibility (E5) blocks them. The review summary shows a warning banner, "N blocking issues are not waived — publication will be refused", so an approver is never misled.

**Review summary snapshot.** At submission, the request stores a frozen JSON snapshot (FR-014): issue counts by severity and state, the version totals by category per currency, the KPI table, and the granted waivers. The review page shows the snapshot **and** the live state, and highlights any difference between them.

---

## 7. Publication Eligibility (PUB-001, PUB-002; PRD §14.2)

```
evaluate_eligibility(version_id, principal) -> EligibilityResult
  checks = []
  v = load_version(version_id)            # missing → stop: VERSION_NOT_FOUND
  E1: principal active ∧ has PUBLISH       → else PERMISSION_DENIED
  E2: v.status == ACTIVE                   → else VERSION_SUPERSEDED
  E3: recompute_content_hash(v) == v.content_hash → else INTEGRITY_FAILURE
  cur  = current_run(v)                    # BR-003; may be None
  last = latest_completed_run(v)           # used by E5/E6 even if E4 fails
  E4: cur exists                           → else NO_CURRENT_VALIDATION (latest run ERROR/RUNNING/none)
                                              or STALE_VALIDATION (last.rule_set != active)
  tuple = (v.id, v.content_hash, last.id, active_rule_set.id)
  E5: for each BLOCKING issue of `last`:
        rule non-waivable                  → NON_WAIVABLE_BLOCKING_ISSUES [issue ids]
        no GRANTED waiver with waiver.tuple == tuple → UNRESOLVED_BLOCKING_ISSUES [issue id, "NO_WAIVER"|"STALE_WAIVER"]
      if last is None                      → UNRESOLVED_BLOCKING_ISSUES ("NO_COMPLETED_RUN")
  E6: approval = latest APPROVE on a request for v
        none                               → MISSING_APPROVAL
        approval.tuple != tuple            → STALE_APPROVAL
        approval.approver == request.submitter → SEGREGATION_OF_DUTIES
  E7: publication exists for (dataset, period) → PERIOD_ALREADY_PUBLISHED
  return {eligible: all passed, checks: [{id, passed, code?, details}]}
```

- Every check runs, except that a missing version stops evaluation, so the result lists every failure.
- The dry run returns the result as it is.
- Publish takes the period lock with `NOWAIT` (failure → `CONCURRENT_PUBLICATION`, which is E8), re-runs the function, and writes only if `eligible` (ARD §8.7).

**Response for an ineligible publish:** `409` with code `PUBLICATION_INELIGIBLE` and the full `checks` array.

---

## 8. Error Codes

All errors use the envelope defined in Document 4 §2.3.

| HTTP | Code | Raised by |
|---|---|---|
| 401 | `UNAUTHENTICATED`, `SESSION_EXPIRED` | All protected endpoints |
| 403 | `PERMISSION_DENIED`, `CSRF_INVALID`, `SEGREGATION_OF_DUTIES`, `ACCOUNT_LOCKED` | Authorisation, CSRF, decisions, login |
| 404 | `NOT_FOUND`, `VERSION_NOT_FOUND` | Lookups |
| 409 | `INVALID_TRANSITION`, `RULE_NOT_WAIVABLE`, `WAIVER_NOT_APPLICABLE`, `NO_CURRENT_VALIDATION`, `VERSION_SUPERSEDED`, `REVIEW_ALREADY_OPEN`, `STALE_REVIEW`, `WARNING_COUNT_MISMATCH`, `RUN_IN_PROGRESS`, `PUBLICATION_INELIGIBLE`, `CONCURRENT_PUBLICATION` | Workflow |
| 413 | `FILE_TOO_LARGE` | Ingestion |
| 422 | `VALIDATION_ERROR`, `INGESTION_STRUCTURAL_ERROR`, `INVALID_PERIOD`, `MISSING_TABLE_FILE`, `CONFIG_INVALID` | Input |
| 500 | `INTERNAL_ERROR` | Unexpected. Never leaks internals; the correlation ID is returned. |

The eligibility check codes E1–E8 (PRD §14.2) appear only inside `checks[].code`. They are never used as top-level error codes, except `CONCURRENT_PUBLICATION`.

---

## 9. Screens (FR-016)

Every screen shows the signed-in user and their roles. Severity and impact category always appear as text labels (FR-016).

| # | Screen | Shows | Actions (role) | Milestone |
|---|---|---|---|---|
| S1 | Sign in | — | Sign in | M1 |
| S2 | Periods | Dataset × period: derived state (§2.1), current version label, blocking and warning counts | Open a period; upload a new period (ANALYST) | M1 |
| S3 | Period detail | Versions (latest first), ingestion attempts and their errors | Upload (ANALYST); open a version | M1 |
| S4 | Version detail | Identity, content hash, schema result, profile (FR-005), runs | Run validation (ANALYST); download raw files (ANALYST, APPROVER); open the review summary | M1 (profile: M3) |
| S5 | Run findings | Findings grouped by severity, `NOT_EVALUATED` rules, counts | Open an issue; open INFO findings | M1 |
| S6 | Issue detail | Message, records (paginated, failing cells marked in text), impact figures with evidence, notes, waiver history, AI panel (M2) | Add a note (ANALYST, APPROVER); request a waiver (ANALYST); grant or deny (APPROVER); request an explanation (M2); export records as CSV | M1 |
| S7 | Impact overview | Version totals by category per currency, KPI table (as reported, adjusted, delta, direction, assumption), supplier ranking | — | M1 |
| S8 | Review summary | Version identity, submission snapshot vs. live state, issues, impacts, waivers, **eligibility checklist (from the dry run)**, review history, blocker banner (§6) | Submit (ANALYST); approve or reject with the warning acknowledgement (APPROVER); publish (ANALYST, APPROVER) | M1 |
| S9 | Publications | List; detail with manifest summary, hashes and `manifest_sha256` | Export ZIP; verify | M1 |
| S10 | Audit | A filterable event list | — | M1 |
| S11 | Users (ADMIN) | Users, roles, active flag | Create, deactivate, change roles; reload configuration | M1 |

---

## 10. M1 Acceptance Mapping

M1 is complete when the following pass with AI disabled:
- PRD §6.1 steps 1–2 and 4–9;
- the PRD §18.2 scenarios N-01 to N-13 and N-15 to N-17;
- every MVP Must Have acceptance criterion outside AI-001 to AI-006.

M2 adds step 3 and N-14 and the AI acceptance criteria. M3 adds FR-005 and PUB-007.
