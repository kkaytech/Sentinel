import { BarChart3, Download, FileStack, Gavel, ListChecks, Play, Rows3, ShieldAlert, TriangleAlert, Users } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ApiError, api, type Page, type Run, type Version } from "../api";
import { useAuth } from "../auth";
import { DataTable } from "../components/DataTable";
import { Badge, Card, Empty, ErrorNotice, Hash, Kpi, Notice, PageHeader, PageLoading, StateBadge } from "../components/ui";
import { count, toApiError, useLoad, when } from "../lib";

export function RunStatus({ run }: { run: Run }) {
  if (run.status === "COMPLETED") return <Badge tone="ok" dot>Completed</Badge>;
  if (run.status === "ERROR") return <Badge tone="danger" dot>Error</Badge>;
  return <Badge tone="warn" dot>Running</Badge>;
}

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
  if (version.loading && !v) return <PageLoading />;
  if (!v) return <ErrorNotice error={version.error} />;
  const current = runs.data?.items.find((r) => r.is_current);
  const canRun = has("ANALYST") && v.status === "ACTIVE" && v.derived_state !== "PUBLISHED";
  const canDownload = has("ANALYST") || has("APPROVER");

  return (
    <>
      <PageHeader
        crumbs={[{ label: "Reporting periods", to: "/periods" }, { label: v.period, to: `/periods/${v.period}` }, { label: v.label }]}
        title={<span className="mono" style={{ fontSize: "inherit" }}>{v.label}</span>}
        badge={<StateBadge state={v.derived_state} />}
        subtitle={<>Uploaded {when(v.created_at)} by {v.created_by.display_name}</>}
        actions={
          <>
            {current && (
              <>
                <Link className="btn" to={`/runs/${current.id}`}>
                  <ListChecks aria-hidden />
                  Findings
                </Link>
                <Link className="btn" to={`/runs/${current.id}/impact`}>
                  <BarChart3 aria-hidden />
                  Impact
                </Link>
                <Link className="btn" to={`/versions/${v.id}/review`}>
                  <Gavel aria-hidden />
                  Review and publish
                </Link>
              </>
            )}
            {canRun && (
              <button className="btn primary" onClick={() => void runValidation()} disabled={busy}>
                <Play aria-hidden />
                {busy ? "Validating…" : current ? "Run validation again" : "Run validation"}
              </button>
            )}
          </>
        }
      />
      <div className="stack">
        <ErrorNotice error={error} />
        {v.status === "SUPERSEDED" && <Notice tone="warn" title="Superseded">A later upload replaced this version. It is kept for the record and cannot be validated or published.</Notice>}
        {v.derived_state === "PUBLISHED" && v.publication_ref && (
          <Notice tone="ok" title="Published">
            This version is published as <Link to={`/publications/${v.publication_ref}`}>{v.publication_ref}</Link>. Its data and validation are sealed.
          </Notice>
        )}
        {v.derived_state === "INGESTED" && runs.data && runs.data.items.length > 0 && v.status === "ACTIVE" && (
          <Notice tone="warn" title="Validation is out of date">The rule set changed after the last run. Run validation again to get current results.</Notice>
        )}
        {busy && <Notice tone="info">Validating every invoice and computing financial impact. Large files take a few seconds.</Notice>}
        <div className="kpis" style={{ marginBottom: 0 }}>
          <Kpi label="Invoices" value={count(v.row_counts.invoices)} icon={Rows3} />
          <Kpi label="Suppliers" value={count(v.row_counts.suppliers)} icon={Users} />
          <Kpi label="Blocking issues" value={current ? v.finding_counts.BLOCKING : "—"} hint={current ? "From the current run" : "Not validated yet"} icon={ShieldAlert} tone={current && v.finding_counts.BLOCKING ? "danger" : current ? "ok" : undefined} />
          <Kpi label="Warnings" value={current ? v.finding_counts.WARNING : "—"} hint={current ? "Acknowledged at approval" : "Not validated yet"} icon={TriangleAlert} tone={current && v.finding_counts.WARNING ? "warn" : undefined} />
        </div>
        <div className="split-wide">
          <Card title="Validation runs" subtitle="The most recent completed run under the active rule set is the current one." flush>
            <ErrorNotice error={runs.error} />
            {runs.data && (
              <DataTable
                rows={runs.data.items}
                rowKey={(r) => r.id}
                onRowClick={(r) => r.status === "COMPLETED" && navigate(`/runs/${r.id}`)}
                empty={<Empty icon={ListChecks} title="Not validated yet">{canRun ? "Run validation to check every invoice against the 32 rules." : "An analyst runs validation for this version."}</Empty>}
                columns={[
                  { key: "started", header: "Started", className: "nowrap", render: (r) => (r.status === "COMPLETED" ? <Link to={`/runs/${r.id}`} onClick={(e) => e.stopPropagation()}>{when(r.started_at)}</Link> : when(r.started_at)) },
                  { key: "status", header: "Status", className: "nowrap", render: (r) => (<span className="row" style={{ gap: 6, flexWrap: "nowrap" }}><RunStatus run={r} />{r.is_current && <Badge tone="accent">Current</Badge>}</span>) },
                  { key: "blocking", header: "Blocking", align: "right", render: (r) => r.finding_counts?.BLOCKING ?? "—" },
                  { key: "warnings", header: "Warnings", align: "right", render: (r) => r.finding_counts?.WARNING ?? "—" },
                  { key: "error", header: "Detail", className: "nowrap", render: (r) => (r.error_detail ? <code className="text-danger">{r.error_detail.type}{r.error_detail.rule_id ? ` in ${r.error_detail.rule_id}` : ""}</code> : <span className="faint">Reference date {r.reference_date}</span>) },
                ]}
              />
            )}
          </Card>
          <Card title="Identity">
            <dl className="props" style={{ gridTemplateColumns: "minmax(96px, 112px) minmax(0, 1fr)" }}>
              <dt>Version ID</dt>
              <dd><Hash value={v.id} /></dd>
              <dt>Content hash</dt>
              <dd><Hash value={v.content_hash} length={24} /><div className="faint" style={{ fontSize: 13 }}>{v.hash_algorithm}</div></dd>
              <dt>Status</dt>
              <dd>{v.status === "ACTIVE" ? "Active" : "Superseded"}</dd>
              <dt>Sequence</dt>
              <dd>Version {v.seq} of period {v.period}</dd>
              {canDownload && (
                <>
                  <dt>Original files</dt>
                  <dd className="row" style={{ gap: 6 }}>
                    {Object.keys(v.columns).map((table) => (
                      <a key={table} className="btn sm" href={api.url(`/versions/${v.id}/raw-files/${table}`)}>
                        <Download aria-hidden />
                        {table}.csv
                      </a>
                    ))}
                  </dd>
                </>
              )}
            </dl>
          </Card>
        </div>
        <Card title="Columns received" subtitle="Contract columns in contract order, then any unexpected columns.">
          <div className="stack-sm">
            {Object.entries(v.columns).map(([table, columns]) => (
              <div key={table} className="row" style={{ alignItems: "flex-start", gap: 10 }}>
                <span className="row nowrap" style={{ width: 150, gap: 6 }}>
                  <FileStack width={15} height={15} className="faint" aria-hidden />
                  <code>{table}.csv</code>
                </span>
                <div className="pill-list" style={{ flex: 1 }}>
                  {columns.map((c) => (
                    <Badge key={c} tone="neutral">{c}</Badge>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </Card>
      </div>
    </>
  );
}
