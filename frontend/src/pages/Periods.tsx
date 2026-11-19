import { CalendarRange } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";
import { DATASET, api, type Page, type PeriodRow } from "../api";
import { useAuth } from "../auth";
import { DataTable } from "../components/DataTable";
import { UploadForm } from "../components/Upload";
import { Card, Empty, ErrorNotice, PageHeader, Skeleton, StateBadge } from "../components/ui";
import { ago, count, useLoad } from "../lib";

export function PeriodsPage() {
  const { has } = useAuth();
  const navigate = useNavigate();
  const { data, error, loading, reload } = useLoad(() => api.get<Page<PeriodRow>>(`/datasets/${DATASET}/periods`), []);
  const now = new Date();
  const lastMonth = new Date(now.getFullYear(), now.getMonth() - 1, 1);
  const defaultPeriod = `${lastMonth.getFullYear()}-${String(lastMonth.getMonth() + 1).padStart(2, "0")}`;

  return (
    <>
      <PageHeader title="Reporting periods" subtitle="Supplier Invoices. Each period can be published once, from its current version." />
      <div className="stack">
        {has("ANALYST") && (
          <Card title="Upload a period" subtitle="Upload suppliers.csv and invoices.csv together. A new upload for an existing period supersedes its current version.">
            <UploadForm defaultPeriod={defaultPeriod} onDone={reload} />
          </Card>
        )}
        <Card title="Periods" subtitle={data ? `${data.total} reporting period${data.total === 1 ? "" : "s"}` : undefined} flush>
          <ErrorNotice error={error} />
          {loading && !data && <Skeleton lines={5} />}
          {data && (
            <DataTable
              rows={data.items}
              rowKey={(p) => p.period}
              onRowClick={(p) => navigate(`/periods/${p.period}`)}
              initialSort={{ key: "period", dir: "desc" }}
              empty={
                <Empty icon={CalendarRange} title="No periods yet">
                  {has("ANALYST") ? "Upload the two files above to create the first period." : "An analyst uploads each period's files."}
                </Empty>
              }
              columns={[
                { key: "period", header: "Period", className: "strong nowrap", sort: (p) => p.period, render: (p) => <Link to={`/periods/${p.period}`} onClick={(e) => e.stopPropagation()}>{p.period}</Link> },
                { key: "state", header: "Status", className: "nowrap", render: (p) => <StateBadge state={p.derived_state} /> },
                {
                  key: "version",
                  header: "Current version",
                  className: "nowrap",
                  render: (p) =>
                    p.current_version ? (
                      <Link to={`/versions/${p.current_version.id}`} onClick={(e) => e.stopPropagation()} className="mono">
                        {p.current_version.label}
                      </Link>
                    ) : (
                      <span className="faint">—</span>
                    ),
                },
                { key: "rows", header: "Invoices", align: "right", sort: (p) => p.current_version?.row_counts.invoices ?? -1, render: (p) => count(p.current_version?.row_counts.invoices) },
                { key: "blocking", header: "Blocking", align: "right", sort: (p) => (p.current_version ? p.blocking_count : -1), render: (p) => (p.current_version ? <span className={p.blocking_count ? "text-danger" : ""}>{p.blocking_count}</span> : "—") },
                { key: "warnings", header: "Warnings", align: "right", sort: (p) => (p.current_version ? p.warning_count : -1), render: (p) => (p.current_version ? <span className={p.warning_count ? "text-warn" : ""}>{p.warning_count}</span> : "—") },
                { key: "uploaded", header: "Last upload", className: "nowrap", render: (p) => (p.current_version ? <span className="muted">{ago(p.current_version.created_at)} · {p.current_version.created_by.display_name}</span> : "—") },
              ]}
            />
          )}
        </Card>
      </div>
    </>
  );
}
