# SENTINEL — ORIGINAL PRODUCT BRIEF

## 1. Product Identity

**Product Name:** Sentinel

**Product Category:** AI-assisted Data Quality and Reporting Governance Platform.

**Product Purpose:**

Sentinel is a pre-publication data quality gate for operational reporting.

Its core question is:

"Can we publish this dataset, and what evidence supports that decision?"

The initial use case is supplier invoice reporting for a small operations or finance analytics team using recurring CSV files and a development PostgreSQL database.

Sentinel is designed to identify data quality issues, quantify their potential reporting consequences, explain findings through evidence-grounded AI, facilitate human review and enforce controlled publication.

## 2. Core Workflow

INGEST → VALIDATE → QUANTIFY REPORTING CONSEQUENCES → EXPLAIN EVIDENCE → REVIEW → APPROVE → PUBLISH

Every stage should have a clear responsibility and produce traceable outputs.

## 3. Core Capabilities

### A. Data Ingestion
- CSV file uploads.
- PostgreSQL data source integration.
- Schema inspection.
- Data profiling.
- Dataset identification and versioning.
- Ingestion history.

### B. Data Validation
- Missing-value detection.
- Duplicate detection.
- Schema and data type validation.
- Invalid business values.
- Cross-table validation.
- Referential integrity checks.
- Supplier and invoice consistency checks.
- Configurable business rules.

### C. Business Impact Analysis
- Identify affected records.
- Quantify potentially affected invoice values.
- Analyse supplier expenditure.
- Identify affected reporting metrics.
- Assess potentially overstated or understated KPIs.
- Explain the evidence behind calculated impacts.

Distinguish confirmed discrepancies from potential financial exposure and estimated reporting impact.

### D. AI Evidence and Explanation Engine
- Explain validation failures.
- Summarise business consequences.
- Generate possible root-cause hypotheses.
- Recommend corrective actions.
- Ground explanations in actual validation results.
- Provide structured outputs and evidence references.

AI must not invent validation findings or independently determine publication eligibility.

### E. Human Review and Approval
- Issue investigation.
- Issue resolution.
- Review requests.
- Approval and rejection.
- Authorised waivers with mandatory justification.
- Role-based permissions.

### F. Publication Engine

Publication must be a real backend-enforced operation.

It must verify:
- Dataset version integrity.
- Current validation results.
- Resolution of blocking issues.
- Required approvals.
- User permissions.
- Publication policy compliance.

Successful publication should create a reproducible snapshot with its dataset version, validation run, approval information, timestamp and publication reference.

Stale validation results and approvals must not authorise publication of modified datasets.

### G. Audit Trail
Track ingestion, validation, issue resolution, waivers, review decisions, approvals, publication attempts and successful publication.

Historical audit events must be protected from ordinary modification.

## 4. Initial Technology Direction

Evaluate the following technologies rather than blindly accepting them.

- Python
- FastAPI
- PostgreSQL
- SQLAlchemy
- Pydantic
- Pandas
- React
- TypeScript
- LLM API integration
- Docker
- Git and GitHub

The preferred architectural approach is a modular monolith.

## 5. Product Boundaries

Sentinel is NOT:
- A generic chatbot.
- An enterprise observability replacement.
- A basic CSV cleaning tool.
- A system where an LLM makes authoritative publication decisions.
- A claim that data quality gates are a newly invented concept.

Its value lies in integrating deterministic data validation, business impact analysis, evidence-grounded AI explanations, human governance and enforceable publication controls into one coherent workflow.

## 6. Portfolio Objective

Build Sentinel as a credible, demonstrable engineering project showcasing:

- Data engineering.
- Data quality engineering.
- SQL and relational database design.
- Applied AI and LLM integration.
- Backend engineering.
- Full-stack development.
- Software architecture.
- Testing and evaluation.
- Security and data governance.

The finished application should demonstrate a complete operational scenario: ingest a deliberately imperfect supplier invoice dataset, identify and validate issues, quantify their potential business consequences, explain findings, facilitate review and successfully publish an approved dataset version.

The implementation must be genuinely functional, tested and documented.

**This document is the original product brief, not the final technical specification. All architectural decisions, functional requirements and implementation details must be developed and reviewed through subsequent engineering documents.**