import { BadgeCheck, CalendarRange, FileCheck2, FileUp, Fingerprint, Gavel, ListChecks, Scale } from "lucide-react";
import { useEffect, useRef } from "react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { DATASET, api, type Page, type PeriodRow } from "../api";
import { useAuth } from "../auth";
import { DataTable } from "../components/DataTable";
import { UploadForm } from "../components/Upload";
import { Card, Empty, ErrorNotice, PageHeader, Skeleton, StateBadge } from "../components/ui";
import { ago, count, useLoad } from "../lib";

const FLOW = [
  { icon: FileUp, title: "Upload", text: "Choose the period and add suppliers.csv and invoices.csv." },
  { icon: Fingerprint, title: "Structural checks and version", text: "Encoding, headers and row shape are checked. Passing files become an immutable, content-hashed version." },
  { icon: ListChecks, title: "Validation", text: "You run the 32 rules from the result or the version page." },
  { icon: Scale, title: "Findings and impact", text: "Inspect each finding and its confirmed discrepancy or potential exposure." },
  { icon: Gavel, title: "Review and approval", text: "Waivers and approval are decided by a second person." },
  { icon: FileCheck2, title: "Publication", text: "Only an approved, eligible version can be published, once per period." },
];

function lastMonth(): string {
  const now = new Date();
  const d = new Date(now.getFullYear(), now.getMonth() - 1, 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

// One page for the periods and for uploading them: the upload sits above the list it adds to.
export function PeriodsPage() {
  const { has } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [params] = useSearchParams();
  const uploadRef = useRef<HTMLElement>(null);
  const { data, error, loading, reload } = useLoad(() => api.get<Page<PeriodRow>>(`/datasets/${DATASET}/periods`), []);
  const requested = params.get("period");
  const period = requested && /^\d{4}-\d{2}$/.test(requested) ? requested : lastMonth();
  const canUpload = has("ANALYST");

  // Links elsewhere ("Upload data", "Upload new version") land on the upload section.
  useEffect(() => {
    if (location.hash === "#upload" && uploadRef.current) {
      uploadRef.current.scrollIntoView({ behavior: "smooth", block: "start" });
      uploadRef.current.querySelector<HTMLInputElement>("#period")?.focus({ preventScroll: true });
    }
  }, [location.key, location.hash]);

  return (
    <>
      <PageHeader
        title="Reporting periods & Uploads"
        subtitle={
          canUpload
            ? "Upload a month of supplier and invoice files, then follow each period from validation to publication. Each period can be published once, from its current version."
            : "Supplier Invoices. Each period can be published once, from its current version."
        }
      />
      <div className="stack">
        {canUpload && (
          <section id="upload" ref={uploadRef} className="split upload-layout" aria-labelledby="upload-title">
            <Card title={<span id="upload-title">Upload data</span>} subtitle="Supplier and invoice CSV files for one period. A new upload for an existing period supersedes its current version." className="upload-card">
              <UploadForm key={period} defaultPeriod={period} periods={data?.items ?? null} onDone={reload} />
            </Card>
            <Card title="From upload to publication" subtitle="Each step is separate. An upload never validates, approves or publishes on its own.">
              <ol className="flow">
                {FLOW.map((step, n) => (
                  <li key={step.title} className={n < 2 ? "here" : ""}>
                    <span className="flow-dot" aria-hidden>
                      <step.icon />
                    </span>
                    <div>
                      <strong>{step.title}</strong>
                      <div className="muted">{step.text}</div>
                    </div>
                  </li>
                ))}
              </ol>
              <div className="divider" />
              <ul className="req-list">
                <li>
                  <BadgeCheck aria-hidden />
                  UTF-8 text, comma-separated, with a header row and the columns listed under each file.
                </li>
                <li>
                  <BadgeCheck aria-hidden />
                  By default up to 20 MB and 200,000 rows per file. The server enforces its configured limits.
                </li>
              </ul>
            </Card>
          </section>
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
                  {canUpload ? "Upload the two files above to create the first period." : "An analyst uploads each period's files."}
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
