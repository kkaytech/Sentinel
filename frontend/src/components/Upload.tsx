import { FileSpreadsheet, FileUp, UploadCloud, X } from "lucide-react";
import { useState, type DragEvent, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { ApiError, DATASET, api, type Attempt, type Version } from "../api";
import { toApiError } from "../lib";
import { DataTable } from "./DataTable";
import { ErrorNotice, Notice } from "./ui";

type Table = "suppliers" | "invoices";
const TABLES: Table[] = ["suppliers", "invoices"];

function size(bytes: number): string {
  if (bytes >= 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  return `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

// Which table a dropped file belongs to, judged by its name.
function guess(file: File): Table | null {
  const name = file.name.toLowerCase();
  if (name.includes("supplier")) return "suppliers";
  if (name.includes("invoice")) return "invoices";
  return null;
}

function Dropzone({ table, file, onFile, onDropMany }: { table: Table; file: File | null; onFile: (file: File | null) => void; onDropMany: (files: File[]) => void }) {
  const [over, setOver] = useState(false);
  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setOver(false);
    const files = Array.from(e.dataTransfer.files);
    if (files.length > 1) onDropMany(files);
    else if (files[0]) onFile(files[0]);
  };
  return (
    <div
      className={`dropzone ${over ? "over" : ""} ${file ? "filled" : ""}`}
      onDragOver={(e) => {
        e.preventDefault();
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={onDrop}
    >
      <input
        id={table}
        type="file"
        accept=".csv,text/csv"
        aria-label={`${table}.csv`}
        onChange={(e) => {
          onFile(e.target.files?.[0] ?? null);
          e.target.value = "";
        }}
      />
      <span className="dropzone-icon" aria-hidden>
        {file ? <FileSpreadsheet /> : <UploadCloud />}
      </span>
      <div className="dropzone-text">
        <div className="dropzone-title">{table}.csv</div>
        <div className="dropzone-meta">{file ? `${file.name} · ${size(file.size)}` : "Drop the file here or click to browse"}</div>
      </div>
      {file && (
        <button type="button" className="icon-btn" aria-label={`Remove ${table}.csv`} onClick={() => onFile(null)}>
          <X />
        </button>
      )}
    </div>
  );
}

export function UploadForm({ fixedPeriod, onDone, defaultPeriod }: { fixedPeriod?: string; defaultPeriod: string; onDone?: () => void }) {
  const navigate = useNavigate();
  const [period, setPeriod] = useState(fixedPeriod ?? defaultPeriod);
  const [files, setFiles] = useState<Record<Table, File | null>>({ suppliers: null, invoices: null });
  const [error, setError] = useState<ApiError | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const assign = (table: Table, file: File | null) => setFiles((f) => ({ ...f, [table]: file }));
  const assignMany = (dropped: File[]) =>
    setFiles((f) => {
      const next = { ...f };
      for (const file of dropped) {
        const table = guess(file);
        if (table) next[table] = file;
      }
      return next;
    });

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setNotice(null);
    const form = new FormData();
    for (const table of TABLES) {
      const file = files[table];
      if (file) form.append(table, file);
    }
    try {
      const result = await api.post<{ attempt: Attempt; version: Version }>(`/datasets/${DATASET}/periods/${encodeURIComponent(period)}/ingestions`, form);
      if (result.attempt.status === "DUPLICATE_CONTENT") {
        setNotice(`These files are identical to ${result.version.label}, so no new version was created.`);
        onDone?.();
      } else {
        navigate(`/versions/${result.version.id}`);
      }
    } catch (err) {
      setError(toApiError(err));
      onDone?.();
    } finally {
      setBusy(false);
    }
  }

  const structural = (error?.details.errors as { table: string; line: number; code: string }[] | undefined) ?? [];
  return (
    <form onSubmit={submit} className="stack" onDragOver={(e) => e.preventDefault()} onDrop={(e) => { e.preventDefault(); assignMany(Array.from(e.dataTransfer.files)); }}>
      <div className="row" style={{ alignItems: "flex-end", gap: 16 }}>
        <div className="field" style={{ width: 200 }}>
          <label className="field-label" htmlFor="period">
            Reporting period
          </label>
          <input id="period" className="input" type="month" value={period} onChange={(e) => setPeriod(e.target.value)} disabled={!!fixedPeriod} required />
        </div>
        <p className="field-hint" style={{ flex: "1 1 260px", paddingBottom: 9 }}>
          UTF-8, comma-separated, with a header row. Up to 20 MB and 200,000 rows per file. Both files are required.
        </p>
      </div>
      <div className="dropzones">
        {TABLES.map((table) => (
          <Dropzone key={table} table={table} file={files[table]} onFile={(f) => assign(table, f)} onDropMany={assignMany} />
        ))}
      </div>
      <ErrorNotice error={error} />
      {error?.code === "INGESTION_STRUCTURAL_ERROR" && structural.length > 0 && (
        <div className="card">
          <div className="card-head">
            <div>
              <h3>Structural errors</h3>
              <div className="card-sub">
                Showing {structural.length} of {String(error.details.total)}. Nothing was stored; fix the file and upload again.
              </div>
            </div>
          </div>
          <DataTable
            columns={[
              { key: "file", header: "File", render: (e) => <code>{e.table}.csv</code> },
              { key: "line", header: "Line", align: "right", render: (e) => e.line },
              { key: "code", header: "Problem", render: (e) => <code>{e.code}</code> },
            ]}
            rows={structural.slice(0, 50)}
            rowKey={(e) => `${e.table}-${e.line}-${e.code}`}
          />
        </div>
      )}
      {notice && <Notice tone="info">{notice}</Notice>}
      <div className="row">
        <button className="btn primary" type="submit" disabled={busy}>
          <FileUp aria-hidden />
          {busy ? "Uploading…" : "Upload"}
        </button>
        <span className="field-hint">The upload creates an immutable, content-hashed version. Validation is run separately.</span>
      </div>
    </form>
  );
}
