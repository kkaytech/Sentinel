import { ArrowRight, Building2, CheckCircle2, FileSpreadsheet, FileUp, Info, ListChecks, Receipt, RotateCcw, ShieldCheck, UploadCloud, X, type LucideIcon } from "lucide-react";
import { useState, type DragEvent, type FormEvent, type ReactNode } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ApiError, DATASET, api, type Attempt, type PeriodRow, type Run, type UploadProgress, type Version } from "../api";
import { useAuth } from "../auth";
import { count, plural, toApiError, useLoad } from "../lib";
import { DataTable } from "./DataTable";
import { Hash, StateBadge } from "./ui";

type Table = "suppliers" | "invoices";
const TABLES: Table[] = ["suppliers", "invoices"];

const TABLE_META: Record<Table, { title: string; icon: LucideIcon; role: string }> = {
  suppliers: { title: "Supplier file", icon: Building2, role: "The supplier master: one row per supplier, with its country, currency and active dates." },
  invoices: { title: "Invoice file", icon: Receipt, role: "The month's invoices and credit notes: one row per document, with amounts and currency." },
};

// What each structural error code means, in plain words. Unknown codes are shown as sent.
const STRUCTURAL: Record<string, string> = {
  MISSING_HEADER: "The header row is missing or does not match the expected columns.",
  DUPLICATE_HEADER: "A column name appears more than once in the header.",
  RAGGED_ROW: "The row has a different number of fields from the header.",
  UNTERMINATED_QUOTE: "A quoted field is opened but never closed.",
  ENCODING_ERROR: "The file is not valid UTF-8 text.",
  ROW_LIMIT_EXCEEDED: "The file has more rows than the upload limit allows.",
};

// Plain-language headings for the backend's rejection codes. The backend message is always shown too.
const REJECTIONS: Record<string, string> = {
  MISSING_TABLE_FILE: "Both files are required",
  FILE_TOO_LARGE: "A file is over the size limit",
  INVALID_PERIOD: "The reporting period is not valid",
  INGESTION_STRUCTURAL_ERROR: "The files failed the structural checks",
  NETWORK_ERROR: "The server could not be reached",
};

interface ContractColumn {
  name: string;
  required?: boolean;
}
type ContractConfig = { contract_version: { contract: { tables: Record<string, { columns: ContractColumn[] }> } } };

export function fileSize(bytes: number): string {
  if (bytes >= 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${bytes} B`;
}

// Which table a dropped file belongs to, judged by its name.
function guess(file: File): Table | null {
  const name = file.name.toLowerCase();
  if (name.includes("supplier")) return "suppliers";
  if (name.includes("invoice")) return "invoices";
  return null;
}

function Dropzone({
  table,
  file,
  columns,
  stored,
  disabled,
  onFile,
  onDropMany,
}: {
  table: Table;
  file: File | null;
  columns: ContractColumn[] | null;
  stored?: Attempt["files"][number];
  disabled: boolean;
  onFile: (file: File | null) => void;
  onDropMany: (files: File[]) => void;
}) {
  const [over, setOver] = useState(false);
  const [showColumns, setShowColumns] = useState(false);
  const meta = TABLE_META[table];
  const notCsv = file && !/\.csv$/i.test(file.name);
  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setOver(false);
    if (disabled) return;
    const files = Array.from(e.dataTransfer.files);
    if (files.length > 1) onDropMany(files);
    else if (files[0]) onFile(files[0]);
  };
  return (
    <div className={`upload-slot ${file ? "filled" : ""}`}>
      <div className="upload-slot-head">
        <span className={`upload-slot-icon ${table}`} aria-hidden>
          <meta.icon />
        </span>
        <div style={{ minWidth: 0 }}>
          <div className="upload-slot-title">
            {meta.title} <code>{table}.csv</code>
          </div>
          <div className="upload-slot-role">{meta.role}</div>
        </div>
      </div>
      <div
        className={`dropzone ${over ? "over" : ""} ${file ? "filled" : ""} ${disabled ? "disabled" : ""}`}
        onDragOver={(e) => {
          e.preventDefault();
          if (!disabled) setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={onDrop}
      >
        <input
          id={table}
          type="file"
          accept=".csv,text/csv"
          aria-label={`${table}.csv`}
          disabled={disabled}
          onChange={(e) => {
            onFile(e.target.files?.[0] ?? null);
            e.target.value = "";
          }}
        />
        <span className="dropzone-icon" aria-hidden>
          {file ? <FileSpreadsheet /> : <UploadCloud />}
        </span>
        <div className="dropzone-text">
          {file ? (
            <>
              <div className="dropzone-title" title={file.name}>
                {file.name}
              </div>
              <div className="dropzone-meta">
                {fileSize(file.size)}
                {stored?.rows != null && <> · {count(stored.rows)} rows parsed</>}
              </div>
            </>
          ) : (
            <>
              <div className="dropzone-title">Drop {table}.csv here</div>
              <div className="dropzone-meta">or browse your files</div>
            </>
          )}
        </div>
        {file ? (
          !disabled && (
            <button type="button" className="icon-btn" aria-label={`Remove ${table}.csv`} onClick={() => onFile(null)}>
              <X />
            </button>
          )
        ) : (
          <span className="btn sm" aria-hidden>
            Browse files
          </span>
        )}
      </div>
      {notCsv && (
        <div className="upload-slot-warn" role="status">
          <Info aria-hidden /> This file does not end in .csv. The server checks its structure and rejects anything that is not comma-separated UTF-8 text.
        </div>
      )}
      {columns && (
        <div className="upload-slot-cols">
          <button type="button" className="link-btn" aria-expanded={showColumns} onClick={() => setShowColumns(!showColumns)}>
            {showColumns ? "Hide" : "Show"} the {columns.length} expected columns
          </button>
          {showColumns && (
            <div className="pill-list" style={{ marginTop: 8 }}>
              {columns.map((c) => (
                <code key={c.name} className={`col-pill ${c.required ? "" : "optional"}`} title={c.required ? "Required" : "Optional"}>
                  {c.name}
                  {!c.required && <span> optional</span>}
                </code>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

type Phase = "idle" | "sending" | "checking" | "done" | "failed";

function Steps({ phase, created }: { phase: Phase; created: boolean | null }) {
  const steps = ["Period and files", "Upload", "Structural checks", "Version"];
  const reached = phase === "idle" ? 0 : phase === "sending" ? 1 : phase === "checking" ? 2 : phase === "done" ? 4 : 2;
  return (
    <ol className="upload-steps" aria-label="Upload progress">
      {steps.map((s, i) => {
        const failed = phase === "failed" && i === 2;
        const state = failed ? "failed" : i < reached ? "done" : i === reached ? "current" : "";
        const label = i === 3 && phase === "done" && created === false ? "Unchanged" : s;
        return (
          <li key={s} className={state} aria-current={state === "current" ? "step" : undefined}>
            <span className="upload-step-dot">{i < reached && !failed ? <CheckCircle2 aria-hidden /> : i + 1}</span>
            {label}
          </li>
        );
      })}
    </ol>
  );
}

// The upload form shared by the upload page and the period screens. It posts to the existing
// ingestion endpoint; the backend performs every check and decides whether a version is created.
// `periods` is the page's own list, reloaded through onDone after each upload; null while it loads.
export function UploadForm({ defaultPeriod, periods, onDone }: { defaultPeriod: string; periods: PeriodRow[] | null; onDone?: () => void }) {
  const navigate = useNavigate();
  const { has } = useAuth();
  const [period, setPeriod] = useState(defaultPeriod);
  const [files, setFiles] = useState<Record<Table, File | null>>({ suppliers: null, invoices: null });
  const [phase, setPhase] = useState<Phase>("idle");
  const [progress, setProgress] = useState<UploadProgress | null>(null);
  const [result, setResult] = useState<{ attempt: Attempt; version: Version; created: boolean } | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [running, setRunning] = useState(false);
  const config = useLoad(() => api.get<ContractConfig>(`/datasets/${DATASET}/config`), []);

  const busy = phase === "sending" || phase === "checking";
  const locked = busy || phase === "done";
  const existing = periods?.find((p) => p.period === period) ?? null;
  const columnsOf = (table: Table) => config.data?.contract_version.contract.tables?.[table]?.columns ?? null;

  const assign = (table: Table, file: File | null) => {
    setFiles((f) => ({ ...f, [table]: file }));
    if (phase === "failed") setPhase("idle");
  };
  const assignMany = (dropped: File[]) =>
    setFiles((f) => {
      const next = { ...f };
      for (const file of dropped) {
        const table = guess(file);
        if (table) next[table] = file;
      }
      return next;
    });

  function reset() {
    setFiles({ suppliers: null, invoices: null });
    setPhase("idle");
    setProgress(null);
    setResult(null);
    setError(null);
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setPhase("sending");
    setProgress(null);
    setError(null);
    setResult(null);
    const form = new FormData();
    for (const table of TABLES) {
      const file = files[table];
      if (file) form.append(table, file);
    }
    try {
      const response = await api.upload<{ attempt: Attempt; version: Version }>(`/datasets/${DATASET}/periods/${encodeURIComponent(period)}/ingestions`, form, (p) => {
        setProgress(p);
        if (p.sent) setPhase("checking");
      });
      setResult({ ...response, created: response.attempt.status === "SUCCEEDED" });
      setPhase("done");
    } catch (err) {
      setError(toApiError(err));
      setPhase("failed");
    } finally {
      onDone?.();
    }
  }

  async function runValidation(version: Version) {
    setRunning(true);
    setError(null);
    try {
      const run = await api.post<Run>(`/versions/${version.id}/runs`);
      navigate(run.status === "COMPLETED" ? `/runs/${run.id}` : `/versions/${version.id}`);
    } catch (err) {
      setError(toApiError(err));
      setRunning(false);
    }
  }

  const structural = (error?.details.errors as { table: string; line: number; code: string }[] | undefined) ?? [];
  const percent = progress && progress.total > 0 ? Math.round((progress.loaded / progress.total) * 100) : null;
  const totalBytes = TABLES.reduce((n, t) => n + (files[t]?.size ?? 0), 0);

  return (
    <form
      onSubmit={submit}
      className="upload stack"
      onDragOver={(e) => e.preventDefault()}
      onDrop={(e) => {
        e.preventDefault();
        if (!locked) assignMany(Array.from(e.dataTransfer.files));
      }}
    >
      <Steps phase={phase} created={result?.created ?? null} />

      <section className="upload-period">
        <div className="field" style={{ width: 220 }}>
          <label className="field-label" htmlFor="period">
            Reporting period
          </label>
          <input id="period" className="input" type="month" value={period} onChange={(e) => setPeriod(e.target.value)} disabled={locked} required />
        </div>
        <div className="upload-period-info" aria-live="polite">
          {periods === null ? (
            <span className="faint">Checking existing periods…</span>
          ) : existing ? (
            <>
              <div className="row" style={{ gap: 8 }}>
                <strong>{existing.period}</strong>
                <StateBadge state={existing.derived_state} />
                {existing.current_version && <span className="mono faint">{existing.current_version.label}</span>}
              </div>
              <div className="muted">
                {phase === "done" && existing.current_version
                  ? `The period's current version is ${existing.current_version.label}.`
                  : existing.derived_state === "PUBLISHED"
                  ? "Already published. A new upload creates a new version for the record, but this period cannot be published again."
                  : existing.current_version
                    ? `Changed files create a new version that supersedes ${existing.current_version.label}, which is kept read-only. Identical files create no new version.`
                    : "Existing period with no active version."}
              </div>
            </>
          ) : period ? (
            <>
              <div className="row" style={{ gap: 8 }}>
                <strong>{period}</strong>
                <span className="badge accent">New period</span>
              </div>
              <div className="muted">The first upload creates version 1 of this period.</div>
            </>
          ) : null}
        </div>
      </section>

      <div className="dropzones">
        {TABLES.map((table) => (
          <Dropzone
            key={table}
            table={table}
            file={files[table]}
            columns={columnsOf(table)}
            stored={result?.attempt.files.find((f) => f.table === table)}
            disabled={locked}
            onFile={(f) => assign(table, f)}
            onDropMany={assignMany}
          />
        ))}
      </div>

      {busy && (
        <div className="upload-progress" role="status" aria-live="polite">
          <div className="row" style={{ justifyContent: "space-between" }}>
            <strong>{phase === "sending" ? "Uploading files" : "Checking structure and creating the version"}</strong>
            <span className="muted num">
              {phase === "sending" ? (percent !== null ? `${percent}% of ${fileSize(totalBytes)}` : `Sending ${fileSize(totalBytes)}…`) : "All bytes sent · waiting for the server"}
            </span>
          </div>
          <div className={`upload-bar ${phase === "checking" || percent === null ? "indeterminate" : ""}`}>
            <span style={phase === "sending" && percent !== null ? { width: `${percent}%` } : undefined} />
          </div>
          <div className="faint" style={{ fontSize: 13 }}>
            {phase === "sending"
              ? "Progress is the share of bytes your browser has sent."
              : "The server parses both files, checks headers, encoding and row shape, hashes the content and stores it in one transaction."}
          </div>
        </div>
      )}

      {error && (
        <div className="notice error" role="alert">
          <X aria-hidden />
          <div className="notice-body">
            <div className="notice-title">{REJECTIONS[error.code] ?? "The upload was rejected"}</div>
            <div>{error.message}</div>
            <div className="mono" style={{ opacity: 0.8, marginTop: 4 }}>
              {error.code}
              {error.status ? ` · HTTP ${error.status}` : ""}
            </div>
            {error.code !== "INGESTION_STRUCTURAL_ERROR" && error.code !== "NETWORK_ERROR" && (
              <div style={{ marginTop: 4 }}>Nothing was stored. Correct the problem and upload again.</div>
            )}
          </div>
        </div>
      )}

      {error?.code === "INGESTION_STRUCTURAL_ERROR" && structural.length > 0 && (
        <div className="card">
          <div className="card-head">
            <div>
              <h3>Structural errors</h3>
              <div className="card-sub">
                Showing {structural.length} of {String(error.details.total)}. No version was created; the failed attempt is kept in the period's ingestion history.
              </div>
            </div>
            <div className="row" style={{ gap: 6 }}>
              {TABLES.map((t) => {
                const n = structural.filter((e) => e.table === t).length;
                return n ? (
                  <span key={t} className="badge danger">
                    {t}.csv · {n}
                  </span>
                ) : null;
              })}
            </div>
          </div>
          <DataTable
            columns={[
              { key: "file", header: "File", render: (e) => <code>{e.table}.csv</code> },
              { key: "line", header: "Line", align: "right", render: (e) => e.line },
              { key: "code", header: "Problem", render: (e) => <code>{e.code}</code> },
              { key: "means", header: "Meaning", className: "wrap", render: (e) => <span className="muted">{STRUCTURAL[e.code] ?? "See the error code."}</span> },
            ]}
            rows={structural.slice(0, 50)}
            rowKey={(e) => `${e.table}-${e.line}-${e.code}`}
          />
        </div>
      )}

      {result && <UploadResult result={result} canRun={has("ANALYST")} running={running} onRun={() => void runValidation(result.version)} onAgain={reset} />}

      {phase !== "done" && (
        <div className="row">
          <button className="btn primary upload-submit" type="submit" disabled={busy}>
            <FileUp aria-hidden />
            {busy ? "Uploading…" : "Upload"}
          </button>
          <span className="field-hint">
            {files.suppliers && files.invoices ? `${fileSize(totalBytes)} in two files.` : "Both files are required."} Uploading creates an immutable, content-hashed version.
          </span>
        </div>
      )}
    </form>
  );
}

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="upload-fact">
      <div className="faint">{label}</div>
      <div>{children}</div>
    </div>
  );
}

function UploadResult({
  result,
  canRun,
  running,
  onRun,
  onAgain,
}: {
  result: { attempt: Attempt; version: Version; created: boolean };
  canRun: boolean;
  running: boolean;
  onRun: () => void;
  onAgain: () => void;
}) {
  const { version, attempt, created } = result;
  return (
    <section className={`upload-result ${created ? "ok" : "same"}`} aria-live="polite">
      <div className="upload-result-head">
        <span className="upload-result-icon" aria-hidden>
          {created ? <CheckCircle2 /> : <Info />}
        </span>
        <div style={{ minWidth: 0 }}>
          <h3>{created ? `Version ${version.label} created` : `No new version: identical to ${version.label}`}</h3>
          <p className="muted">
            {created
              ? version.seq > 1
                ? `Both files passed the structural checks. This version supersedes version ${version.seq - 1}, which is kept read-only.`
                : "Both files passed the structural checks. This is the first version of the period."
              : "The content hash matches the period's current version, so nothing new was stored. The attempt is recorded."}
          </p>
        </div>
      </div>
      <div className="upload-facts">
        <Fact label="Period">{version.period}</Fact>
        <Fact label="Suppliers">{count(version.row_counts.suppliers)} rows</Fact>
        <Fact label="Invoices">{count(version.row_counts.invoices)} rows</Fact>
        <Fact label="Status">
          <StateBadge state={version.derived_state} />
        </Fact>
        <Fact label="Content hash">
          <Hash value={version.content_hash} length={16} />
        </Fact>
        <Fact label="Files">{plural(attempt.files.length, "file")} · {fileSize(attempt.files.reduce((n, f) => n + f.size_bytes, 0))}</Fact>
      </div>
      <div className="upload-next">
        <ShieldCheck aria-hidden />
        <div style={{ flex: 1, minWidth: 0 }}>
          <strong>Next: run validation.</strong> The 32 rules check every invoice; findings and financial impact follow. Approval and publication stay separate steps.
        </div>
      </div>
      <div className="row">
        {canRun && (
          <button type="button" className="btn primary" onClick={onRun} disabled={running}>
            <ListChecks aria-hidden />
            {running ? "Validating…" : "Run validation"}
          </button>
        )}
        <Link className="btn" to={`/versions/${version.id}`}>
          Open version
          <ArrowRight aria-hidden />
        </Link>
        <button type="button" className="btn ghost" onClick={onAgain}>
          <RotateCcw aria-hidden />
          Upload other files
        </button>
      </div>
    </section>
  );
}
