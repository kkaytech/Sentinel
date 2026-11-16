-- PoC-1 tables (ARD §10.1). Applied as sentinel_owner on top of migrations 0001-0003.
-- These mirror the shapes in Doc 4 §4.5-§4.9 closely enough to measure them; they are NOT the
-- production migrations. Only what the workloads touch is created.

CREATE TABLE app.dataset_versions (
    id uuid PRIMARY KEY,
    label text NOT NULL UNIQUE,
    contract_version_id uuid NOT NULL,
    content_hash char(64) NOT NULL,
    hash_algorithm text NOT NULL,
    columns jsonb NOT NULL,
    row_counts jsonb NOT NULL,
    status text NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'SUPERSEDED')),
    created_at timestamptz NOT NULL DEFAULT now(),
    creating_xact xid8 NOT NULL DEFAULT pg_current_xact_id()
);

CREATE TABLE data.raw_files (
    dataset_version_id uuid NOT NULL REFERENCES app.dataset_versions,
    table_name text NOT NULL,
    filename text NOT NULL,
    sha256 char(64) NOT NULL,
    size_bytes int NOT NULL,
    bytes bytea NOT NULL,
    PRIMARY KEY (dataset_version_id, table_name)
);

-- ADR-006 variant A: raw text cells in one generic table, primary key index only.
CREATE TABLE data.version_rows (
    dataset_version_id uuid NOT NULL REFERENCES app.dataset_versions,
    table_name text NOT NULL,
    row_num int NOT NULL,
    cells jsonb NOT NULL,
    PRIMARY KEY (dataset_version_id, table_name, row_num)
);

CREATE TRIGGER raw_files_seal BEFORE INSERT ON data.raw_files FOR EACH ROW
    EXECUTE FUNCTION app.sentinel_seal_guard('app.dataset_versions', 'dataset_version_id');
CREATE TRIGGER version_rows_seal BEFORE INSERT ON data.version_rows FOR EACH ROW
    EXECUTE FUNCTION app.sentinel_seal_guard('app.dataset_versions', 'dataset_version_id');

CREATE TABLE app.validation_runs (
    id uuid PRIMARY KEY,
    dataset_version_id uuid NOT NULL REFERENCES app.dataset_versions,
    period char(7) NOT NULL,
    reference_date date NOT NULL,
    status text NOT NULL CHECK (status IN ('RUNNING', 'COMPLETED', 'ERROR'))
);

CREATE TABLE app.findings (
    id uuid PRIMARY KEY,
    run_id uuid NOT NULL REFERENCES app.validation_runs,
    rule_id text NOT NULL,
    UNIQUE (run_id, rule_id)
);

CREATE TABLE app.finding_records (
    finding_id uuid NOT NULL REFERENCES app.findings,
    ordinal int NOT NULL,
    row_num int NOT NULL,
    record_key text NOT NULL,
    group_no int,
    is_canonical bool,
    PRIMARY KEY (finding_id, ordinal)
);
CREATE INDEX finding_records_row ON app.finding_records (finding_id, row_num);

-- `currency` is text here: an invalid code longer than 3 characters must not break the run.
CREATE TABLE app.run_impact_totals (
    run_id uuid NOT NULL REFERENCES app.validation_runs,
    category text NOT NULL CHECK (category IN ('CONFIRMED_DISCREPANCY', 'POTENTIAL_EXPOSURE')),
    currency text NOT NULL,
    amount numeric(18,2) NOT NULL,
    record_count int NOT NULL,
    unquantifiable_count int NOT NULL,
    PRIMARY KEY (run_id, category, currency)
);

CREATE TABLE app.kpi_values (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id uuid NOT NULL REFERENCES app.validation_runs,
    kpi_id text NOT NULL,
    scope text NOT NULL CHECK (scope IN ('AS_REPORTED', 'ISSUE', 'FULLY_ADJUSTED')),
    currency text NOT NULL,
    supplier_id text,
    value numeric(20,2) NOT NULL
);
CREATE INDEX kpi_values_run ON app.kpi_values (run_id, kpi_id, scope);

CREATE TABLE app.publications (
    id uuid PRIMARY KEY,
    dataset_version_id uuid NOT NULL REFERENCES app.dataset_versions,
    creating_xact xid8 NOT NULL DEFAULT pg_current_xact_id()
);

CREATE TABLE published.suppliers (
    publication_id uuid NOT NULL REFERENCES app.publications,
    supplier_id text NOT NULL,
    supplier_name text,
    country_code text,
    default_currency text,
    status text,
    active_from date,
    active_to date,
    tax_id text,
    PRIMARY KEY (publication_id, supplier_id)
);

CREATE TABLE published.invoices (
    publication_id uuid NOT NULL REFERENCES app.publications,
    invoice_id text NOT NULL,
    supplier_id text,
    supplier_invoice_number text,
    document_type text,
    invoice_date date,
    due_date date,
    currency text NOT NULL,
    net_amount numeric(18,2),
    tax_amount numeric(18,2),
    gross_amount numeric(18,2) NOT NULL,
    status text,
    description text,
    PRIMARY KEY (publication_id, invoice_id)
);

CREATE TRIGGER suppliers_seal BEFORE INSERT ON published.suppliers FOR EACH ROW
    EXECUTE FUNCTION app.sentinel_seal_guard('app.publications', 'publication_id');
CREATE TRIGGER invoices_seal BEFORE INSERT ON published.invoices FOR EACH ROW
    EXECUTE FUNCTION app.sentinel_seal_guard('app.publications', 'publication_id');

-- The application role gets insert-only access, as in ARD §7.3.2.
GRANT SELECT, INSERT ON ALL TABLES IN SCHEMA app, data, published TO sentinel_app;
