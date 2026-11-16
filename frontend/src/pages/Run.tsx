import { Link, NavLink, useParams } from "react-router-dom";
import { api, type Finding, type Page, type Run, type Version } from "../api";
import { Card, Empty, ErrorBox, Loading, Severity, useLoad, when } from "../ui";

export function RunHeader({ run, version }: { run: Run; version: Version | null }) {
  return (
    <>
      <div className="crumbs">
        <Link to="/periods">Periods</Link> / <Link to={`/periods/${run.period}`}>{run.period}</Link> /{" "}
        <Link to={`/versions/${run.dataset_version_id}`}>{version?.label ?? "version"}</Link> / run
      </div>
      <div className="page-head">
        <div>
          <h1>Validation run</h1>
          <p className="muted">
            {version?.label} · started {when(run.started_at)} · reference date {run.reference_date} · engine {run.engine_version}
          </p>
        </div>
      </div>
      {!run.is_current && <div className="alert warn">This is not the current run for its version. Its results are kept for the record only.</div>}
      <div className="tabs">
        <NavLink to={`/runs/${run.id}`} end>
          Findings
        </NavLink>
        <NavLink to={`/runs/${run.id}/impact`}>Reporting impact</NavLink>
      </div>
    </>
  );
}

export function useRun(runId: string) {
  const run = useLoad(() => api.get<Run>(`/runs/${runId}`), [runId]);
  const versionId = run.data?.dataset_version_id;
  const version = useLoad(() => (versionId ? api.get<Version>(`/versions/${versionId}`) : Promise.resolve(null)), [versionId]);
  return { run, version: version.data };
}

const GROUPS: { severity: Finding["severity"]; title: string; note: string }[] = [
  { severity: "BLOCKING", title: "Blocking", note: "Must be fixed at source or waived before publication." },
  { severity: "WARNING", title: "Warnings", note: "Do not block publication. The approver acknowledges them." },
  { severity: "INFO", title: "Information", note: "For awareness only." },
];

export function RunPage() {
  const { runId = "" } = useParams();
  const { run, version } = useRun(runId);
  const findings = useLoad(() => api.get<Page<Finding>>(`/runs/${runId}/findings`), [runId]);
  const r = run.data;
  return (
    <>
      <ErrorBox error={run.error ?? findings.error} />
      {run.loading && !r && <Loading />}
      {r && (
        <>
          <RunHeader run={r} version={version} />
          <div className="grid" style={{ marginBottom: 16 }}>
            {GROUPS.map((g) => (
              <div className="stat" key={g.severity}>
                <div className="label">{g.title}</div>
                <div className="value">{r.finding_counts?.[g.severity] ?? "—"}</div>
              </div>
            ))}
            <div className="stat">
              <div className="label">Rules not evaluated</div>
              <div className="value">{r.not_evaluated.length}</div>
            </div>
          </div>
          {findings.data && findings.data.items.length === 0 && (
            <div className="alert ok">No findings. Every rule that could be evaluated passed.</div>
          )}
          {GROUPS.map((g) => {
            const items = findings.data?.items.filter((f) => f.severity === g.severity) ?? [];
            if (items.length === 0) return null;
            return (
              <Card key={g.severity} title={`${g.title} (${items.length})`}>
                <p className="muted" style={{ marginTop: 0 }}>{g.note}</p>
                <table>
                  <thead>
                    <tr>
                      <th>Severity</th>
                      <th>Rule</th>
                      <th>Finding</th>
                      <th className="num">Records</th>
                      <th>Waivable</th>
                    </tr>
                  </thead>
                  <tbody>
                    {items.map((f) => (
                      <tr key={f.id}>
                        <td>
                          <Severity value={f.severity} />
                        </td>
                        <td className="mono">
                          <Link to={`/findings/${f.id}`}>{f.rule_id}</Link>
                        </td>
                        <td>{f.message}</td>
                        <td className="num">{f.failing_count.toLocaleString()}</td>
                        <td>{f.severity !== "BLOCKING" ? "n/a" : f.waivable ? "Yes" : "No — fix at source"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </Card>
            );
          })}
          {r.not_evaluated.length > 0 && (
            <Card title={`Not evaluated (${r.not_evaluated.length})`}>
              <p className="muted" style={{ marginTop: 0 }}>These rules need a required column that is missing from the upload.</p>
              <table>
                <thead>
                  <tr>
                    <th>Rule</th>
                    <th>Missing columns</th>
                  </tr>
                </thead>
                <tbody>
                  {r.not_evaluated.map((n) => (
                    <tr key={n.rule_id}>
                      <td className="mono">{n.rule_id}</td>
                      <td>{n.missing_columns.join(", ")}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Card>
          )}
          {findings.loading && !findings.data && <Loading what="Loading findings" />}
          {!findings.loading && !findings.data && <Empty>Findings are unavailable.</Empty>}
        </>
      )}
    </>
  );
}
