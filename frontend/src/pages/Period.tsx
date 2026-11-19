import { CheckCircle2, CopyCheck, History, XCircle } from "lucide-react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { DATASET, api, type Attempt, type PeriodDetail } from "../api";
import { useAuth } from "../auth";
import { DataTable } from "../components/DataTable";
import { UploadForm } from "../components/Upload";
import { Badge, Card, Empty, ErrorNotice, Hash, PageHeader, PageLoading, StateBadge } from "../components/ui";
import { count, short, useLoad, when } from "../lib";

function AttemptOutcome({ attempt }: { attempt: Attempt }) {
  if (attempt.status === "SUCCEEDED") return <Badge tone="ok"><CheckCircle2 aria-hidden />Accepted</Badge>;
  if (attempt.status === "DUPLICATE_CONTENT") return <Badge tone="info"><CopyCheck aria-hidden />Duplicate content</Badge>;
  return <Badge tone="danger"><XCircle aria-hidden />Rejected</Badge>;
}

export function PeriodPage() {
  const { period = "" } = useParams();
  const { has } = useAuth();
  const navigate = useNavigate();
  const { data, error, loading, reload } = useLoad(() => api.get<PeriodDetail>(`/datasets/${DATASET}/periods/${period}`), [period]);
  if (loading && !data) return <PageLoading />;
  const current = data?.versions.find((v) => v.status === "ACTIVE");

  return (
    <>
      <PageHeader
        crumbs={[{ label: "Reporting periods", to: "/periods" }, { label: period }]}
        title={`Period ${period}`}
        badge={current ? <StateBadge state={current.derived_state} /> : undefined}
        subtitle={current ? <>Current version <Link to={`/versions/${current.id}`} className="mono">{current.label}</Link></> : "No version has been created for this period yet."}
        actions={current ? <Link className="btn primary" to={`/versions/${current.id}`}>Open current version</Link> : undefined}
      />
      <div className="stack">
        <ErrorNotice error={error} />
        {data && (
          <Card title="Version history" subtitle="Every upload that changed the content. Earlier versions are kept, read-only." flush>
            <DataTable
              rows={data.versions}
              rowKey={(v) => v.id}
              onRowClick={(v) => navigate(`/versions/${v.id}`)}
              empty={<Empty icon={History} title="No versions">Upload both files to create the first version.</Empty>}
              columns={[
                { key: "label", header: "Version", className: "nowrap", render: (v) => <Link to={`/versions/${v.id}`} className="mono" onClick={(e) => e.stopPropagation()}>{v.label}</Link> },
                { key: "state", header: "Status", className: "nowrap", render: (v) => <StateBadge state={v.derived_state} /> },
                { key: "invoices", header: "Invoices", align: "right", render: (v) => count(v.row_counts.invoices) },
                { key: "suppliers", header: "Suppliers", align: "right", render: (v) => count(v.row_counts.suppliers) },
                { key: "issues", header: "Blocking / warnings", align: "right", render: (v) => (v.status === "ACTIVE" && v.derived_state !== "INGESTED" ? `${v.finding_counts.BLOCKING} / ${v.finding_counts.WARNING}` : "—") },
                { key: "hash", header: "Content hash", render: (v) => <code className="faint">{short(v.content_hash, 14)}</code> },
                { key: "uploaded", header: "Uploaded", className: "nowrap", render: (v) => <span className="muted">{when(v.created_at)} · {v.created_by.display_name}</span> },
              ]}
            />
          </Card>
        )}
        {has("ANALYST") && (
          <Card title="Upload a new version" subtitle="Corrections are made by uploading again. The current version is superseded and kept for the record.">
            <UploadForm fixedPeriod={period} defaultPeriod={period} onDone={reload} />
          </Card>
        )}
        {data && (
          <Card title="Ingestion attempts" subtitle="Every upload, including rejected ones and unchanged re-uploads." flush>
            <DataTable
              rows={data.ingestion_attempts}
              rowKey={(a) => a.id}
              empty={<Empty compact title="No uploads recorded" />}
              columns={[
                { key: "when", header: "Started", className: "nowrap", render: (a) => when(a.started_at) },
                { key: "outcome", header: "Outcome", className: "nowrap", render: (a) => <AttemptOutcome attempt={a} /> },
                {
                  key: "files",
                  header: "Files",
                  render: (a) => (
                    <div className="stack-sm" style={{ gap: 2 }}>
                      {a.files.map((f) => (
                        <div key={f.table} className="nowrap">
                          <code>{f.filename}</code> <span className="faint">· {f.rows === null ? "?" : count(f.rows)} rows · <Hash value={f.sha256} length={10} /></span>
                        </div>
                      ))}
                    </div>
                  ),
                },
                {
                  key: "detail",
                  header: "Detail",
                  className: "wrap",
                  render: (a) =>
                    a.errors?.errors ? (
                      <span>
                        {a.errors.total} structural error(s); first: {a.errors.errors[0]?.table}.csv line {a.errors.errors[0]?.line} <code>{a.errors.errors[0]?.code}</code>
                      </span>
                    ) : a.errors?.code ? (
                      <code>{a.errors.code}</code>
                    ) : (
                      <span className="faint">—</span>
                    ),
                },
              ]}
            />
          </Card>
        )}
      </div>
    </>
  );
}
