import { Link, useParams } from "react-router-dom";
import { DATASET, api, type PeriodDetail } from "../api";
import { useAuth } from "../auth";
import { Card, Empty, ErrorBox, Loading, StateBadge, short, useLoad, when } from "../ui";
import { UploadForm } from "./Periods";

export function PeriodPage() {
  const { period = "" } = useParams();
  const { has } = useAuth();
  const { data, error, loading, reload } = useLoad(
    () => api.get<PeriodDetail>(`/datasets/${DATASET}/periods/${period}`),
    [period],
  );
  return (
    <>
      <div className="crumbs">
        <Link to="/periods">Periods</Link> / {period}
      </div>
      <div className="page-head">
        <h1>Period {period}</h1>
      </div>
      <ErrorBox error={error} />
      {loading && !data && <Loading />}
      {has("ANALYST") && (
        <Card title="Upload a new version">
          <p className="muted">Corrections are made by uploading again. The earlier version is kept and marked superseded.</p>
          <UploadForm fixedPeriod={period} onDone={reload} />
        </Card>
      )}
      {data && (
        <>
          <Card title="Versions">
            {data.versions.length === 0 ? (
              <Empty>No version has been created for this period.</Empty>
            ) : (
              <table>
                <thead>
                  <tr>
                    <th>Version</th>
                    <th>State</th>
                    <th className="num">Invoices</th>
                    <th className="num">Suppliers</th>
                    <th>Content hash</th>
                    <th>Uploaded</th>
                  </tr>
                </thead>
                <tbody>
                  {data.versions.map((v) => (
                    <tr key={v.id}>
                      <td>
                        <Link to={`/versions/${v.id}`}>{v.label}</Link>
                      </td>
                      <td>
                        <StateBadge state={v.derived_state} />
                      </td>
                      <td className="num">{v.row_counts.invoices ?? "—"}</td>
                      <td className="num">{v.row_counts.suppliers ?? "—"}</td>
                      <td className="mono">{short(v.content_hash)}</td>
                      <td>
                        {when(v.created_at)} by {v.created_by.display_name}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Card>
          <Card title="Ingestion attempts">
            {data.ingestion_attempts.length === 0 ? (
              <Empty>No uploads recorded.</Empty>
            ) : (
              <table>
                <thead>
                  <tr>
                    <th>Started</th>
                    <th>Outcome</th>
                    <th>Files</th>
                    <th>Detail</th>
                  </tr>
                </thead>
                <tbody>
                  {data.ingestion_attempts.map((a) => (
                    <tr key={a.id}>
                      <td>{when(a.started_at)}</td>
                      <td>
                        <span className={`badge ${a.status === "FAILED" ? "sev-blocking" : a.status === "SUCCEEDED" ? "ok" : ""}`}>{a.status}</span>
                      </td>
                      <td>
                        {a.files.map((f) => (
                          <div key={f.table}>
                            {f.filename} <span className="muted">({f.rows ?? "?"} rows, sha256 {short(f.sha256, 10)})</span>
                          </div>
                        ))}
                      </td>
                      <td>
                        {a.errors?.errors
                          ? `${a.errors.total} structural error(s); first: ${a.errors.errors[0]?.table}.csv line ${a.errors.errors[0]?.line} ${a.errors.errors[0]?.code}`
                          : (a.errors?.code ?? "—")}
                      </td>
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
