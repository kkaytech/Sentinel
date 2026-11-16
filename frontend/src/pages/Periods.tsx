import { useRef, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ApiError, DATASET, api, type Attempt, type Page, type PeriodRow, type Version } from "../api";
import { useAuth } from "../auth";
import { Card, Empty, ErrorBox, Loading, StateBadge, toApiError, useLoad } from "../ui";

function currentPeriod(): string {
  return new Date().toISOString().slice(0, 7);
}

export function UploadForm({ fixedPeriod, onDone }: { fixedPeriod?: string; onDone?: () => void }) {
  const navigate = useNavigate();
  const [period, setPeriod] = useState(fixedPeriod ?? currentPeriod());
  const suppliers = useRef<HTMLInputElement>(null);
  const invoices = useRef<HTMLInputElement>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setNotice(null);
    const form = new FormData();
    const s = suppliers.current?.files?.[0];
    const i = invoices.current?.files?.[0];
    if (s) form.append("suppliers", s);
    if (i) form.append("invoices", i);
    try {
      const result = await api.post<{ attempt: Attempt; version: Version }>(
        `/datasets/${DATASET}/periods/${encodeURIComponent(period)}/ingestions`,
        form,
      );
      if (result.attempt.status === "DUPLICATE_CONTENT") {
        setNotice(`These files are identical to ${result.version.label}. No new version was created.`);
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
    <form onSubmit={submit}>
      <ErrorBox error={error} />
      {error?.code === "INGESTION_STRUCTURAL_ERROR" && (
        <div className="alert warn">
          Showing {structural.length} of {String(error.details.total)} structural errors:
          <ul>
            {structural.slice(0, 20).map((e, n) => (
              <li key={n}>
                {e.table}.csv line {e.line}: {e.code}
              </li>
            ))}
          </ul>
        </div>
      )}
      {notice && <div className="alert info">{notice}</div>}
      <div className="row">
        <div className="field">
          <label htmlFor="period">Reporting period</label>
          <input id="period" type="month" value={period} onChange={(e) => setPeriod(e.target.value)} disabled={!!fixedPeriod} required />
        </div>
        <div className="field">
          <label htmlFor="suppliers">suppliers.csv</label>
          <input id="suppliers" type="file" accept=".csv,text/csv" ref={suppliers} />
        </div>
        <div className="field">
          <label htmlFor="invoices">invoices.csv</label>
          <input id="invoices" type="file" accept=".csv,text/csv" ref={invoices} />
        </div>
        <div className="field">
          <button className="primary" type="submit" disabled={busy}>
            {busy ? "Uploading…" : "Upload"}
          </button>
        </div>
      </div>
    </form>
  );
}

export function PeriodsPage() {
  const { has } = useAuth();
  const { data, error, loading, reload } = useLoad(() => api.get<Page<PeriodRow>>(`/datasets/${DATASET}/periods`), []);
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Reporting periods</h1>
          <p className="muted">Supplier Invoices ({DATASET}). One publishable version per period.</p>
        </div>
      </div>
      {has("ANALYST") && (
        <Card title="Upload a period">
          <UploadForm onDone={reload} />
        </Card>
      )}
      <Card title="Periods">
        <ErrorBox error={error} />
        {loading && !data && <Loading />}
        {data && data.items.length === 0 && <Empty>No periods yet. Upload suppliers.csv and invoices.csv to begin.</Empty>}
        {data && data.items.length > 0 && (
          <table>
            <thead>
              <tr>
                <th>Period</th>
                <th>State</th>
                <th>Current version</th>
                <th className="num">Blocking</th>
                <th className="num">Warnings</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((p) => (
                <tr key={p.period}>
                  <td>
                    <Link to={`/periods/${p.period}`}>{p.period}</Link>
                  </td>
                  <td>
                    <StateBadge state={p.derived_state} />
                  </td>
                  <td>{p.current_version ? <Link to={`/versions/${p.current_version.id}`}>{p.current_version.label}</Link> : "—"}</td>
                  <td className="num">{p.current_version ? p.blocking_count : "—"}</td>
                  <td className="num">{p.current_version ? p.warning_count : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </>
  );
}
