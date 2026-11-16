import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ApiError, api, type Page, type Run, type Version } from "../api";
import { useAuth } from "../auth";
import { Card, Empty, ErrorBox, Loading, StateBadge, toApiError, useLoad, when } from "../ui";

export function VersionPage() {
  const { versionId = "" } = useParams();
  const { has } = useAuth();
  const navigate = useNavigate();
  const version = useLoad(() => api.get<Version>(`/versions/${versionId}`), [versionId]);
  const runs = useLoad(() => api.get<Page<Run>>(`/versions/${versionId}/runs`), [versionId]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

  async function runValidation() {
    setBusy(true);
    setError(null);
    try {
      const run = await api.post<Run>(`/versions/${versionId}/runs`);
      if (run.status === "COMPLETED") navigate(`/runs/${run.id}`);
      else {
        version.reload();
        runs.reload();
      }
    } catch (err) {
      setError(toApiError(err));
    } finally {
      setBusy(false);
    }
  }

  const v = version.data;
  const current = runs.data?.items.find((r) => r.is_current);
  const canDownload = has("ANALYST") || has("APPROVER");
  return (
    <>
      <div className="crumbs">
        <Link to="/periods">Periods</Link> / {v && <Link to={`/periods/${v.period}`}>{v.period}</Link>} / {v?.label}
      </div>
      <ErrorBox error={version.error ?? error} />
      {version.loading && !v && <Loading />}
      {v && (
        <>
          <div className="page-head">
            <div>
              <h1>
                {v.label} <StateBadge state={v.derived_state} />
              </h1>
              <p className="muted">
                Uploaded {when(v.created_at)} by {v.created_by.display_name}
              </p>
            </div>
            <div className="actions">
              {current && (
                <>
                  <Link className="button" to={`/runs/${current.id}`}>
                    Findings
                  </Link>
                  <Link className="button" to={`/runs/${current.id}/impact`}>
                    Impact
                  </Link>
                  <Link className="button" to={`/versions/${v.id}/review`}>
                    Review and publish
                  </Link>
                </>
              )}
              {has("ANALYST") && v.status === "ACTIVE" && v.derived_state !== "PUBLISHED" && (
                <button className="primary" onClick={() => void runValidation()} disabled={busy}>
                  {busy ? "Validating…" : current ? "Run validation again" : "Run validation"}
                </button>
              )}
            </div>
          </div>
          {v.status === "SUPERSEDED" && <div className="alert warn">This version has been superseded by a later upload. It is kept for the record and cannot be validated or published.</div>}
          {v.derived_state === "INGESTED" && runs.data && runs.data.items.length > 0 && (
            <div className="alert warn">The rule set has changed since the last run. Run validation again to get current results.</div>
          )}
          <div className="grid" style={{ marginBottom: 16 }}>
            <div className="stat">
              <div className="label">Invoices</div>
              <div className="value">{v.row_counts.invoices?.toLocaleString() ?? "—"}</div>
            </div>
            <div className="stat">
              <div className="label">Suppliers</div>
              <div className="value">{v.row_counts.suppliers?.toLocaleString() ?? "—"}</div>
            </div>
            <div className="stat">
              <div className="label">Blocking issues</div>
              <div className="value">{current ? v.finding_counts.BLOCKING : "—"}</div>
            </div>
            <div className="stat">
              <div className="label">Warnings</div>
              <div className="value">{current ? v.finding_counts.WARNING : "—"}</div>
            </div>
          </div>
          <Card title="Identity">
            <dl className="facts">
              <dt>Version ID</dt>
              <dd className="mono">{v.id}</dd>
              <dt>Content hash ({v.hash_algorithm})</dt>
              <dd className="mono">{v.content_hash}</dd>
              <dt>Status</dt>
              <dd>{v.status}</dd>
              {Object.entries(v.columns).map(([table, columns]) => (
                <div key={table} style={{ display: "contents" }}>
                  <dt>Columns in {table}.csv</dt>
                  <dd>{columns.join(", ")}</dd>
                </div>
              ))}
              {canDownload && (
                <>
                  <dt>Original files</dt>
                  <dd>
                    {Object.keys(v.columns).map((table) => (
                      <a key={table} href={api.url(`/versions/${v.id}/raw-files/${table}`)} style={{ marginRight: 14 }}>
                        {table}.csv
                      </a>
                    ))}
                  </dd>
                </>
              )}
            </dl>
          </Card>
          <Card title="Validation runs">
            <ErrorBox error={runs.error} />
            {runs.data && runs.data.items.length === 0 && <Empty>This version has not been validated yet.</Empty>}
            {runs.data && runs.data.items.length > 0 && (
              <table>
                <thead>
                  <tr>
                    <th>Started</th>
                    <th>Status</th>
                    <th>Current</th>
                    <th className="num">Blocking</th>
                    <th className="num">Warnings</th>
                    <th className="num">Info</th>
                    <th>Reference date</th>
                  </tr>
                </thead>
                <tbody>
                  {runs.data.items.map((r) => (
                    <tr key={r.id}>
                      <td>{r.status === "COMPLETED" ? <Link to={`/runs/${r.id}`}>{when(r.started_at)}</Link> : when(r.started_at)}</td>
                      <td>
                        <span className={`badge ${r.status === "ERROR" ? "sev-blocking" : r.status === "COMPLETED" ? "ok" : "sev-warning"}`}>{r.status}</span>
                        {r.error_detail && <span className="muted"> {r.error_detail.type}{r.error_detail.rule_id ? ` in ${r.error_detail.rule_id}` : ""}</span>}
                      </td>
                      <td>{r.is_current ? "Yes" : "No"}</td>
                      <td className="num">{r.finding_counts?.BLOCKING ?? "—"}</td>
                      <td className="num">{r.finding_counts?.WARNING ?? "—"}</td>
                      <td className="num">{r.finding_counts?.INFO ?? "—"}</td>
                      <td>{r.reference_date}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Card>
        </>
      )}
    </>
  );
}
