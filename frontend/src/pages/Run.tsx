import { BarChart3, CheckCircle2, Gavel, ListChecks, Search, SearchX } from "lucide-react";
import { useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { DATASET, api, type Finding, type Issue, type Page, type Run, type Version } from "../api";
import { Legend, StackBar } from "../components/Charts";
import { DataTable } from "../components/DataTable";
import { Badge, Card, Empty, ErrorNotice, IssueState, Notice, PageHeader, PageLoading, Segmented, Severity, Skeleton, Tabs } from "../components/ui";
import { count, useLoad, when } from "../lib";

interface RuleConfig {
  id: string;
  name: string;
  type: string;
  severity: string;
  table: string;
}

export function useRun(runId: string) {
  const run = useLoad(() => api.get<Run>(`/runs/${runId}`), [runId]);
  const versionId = run.data?.dataset_version_id;
  const version = useLoad(() => (versionId ? api.get<Version>(`/versions/${versionId}`) : Promise.resolve(null)), [versionId]);
  return { run, version: version.data };
}

export function RunHeader({ run, version, title }: { run: Run; version: Version | null; title: string }) {
  return (
    <>
      <PageHeader
        crumbs={[
          { label: "Reporting periods", to: "/periods" },
          { label: run.period, to: `/periods/${run.period}` },
          { label: version?.label ?? "Version", to: `/versions/${run.dataset_version_id}` },
          { label: title },
        ]}
        title={title}
        badge={run.is_current ? <Badge tone="accent" dot>Current run</Badge> : <Badge tone="neutral" dot>Not current</Badge>}
        subtitle={
          <>
            {version?.label} · run {when(run.started_at)} · reference date {run.reference_date} · engine {run.engine_version}
          </>
        }
      />
      {!run.is_current && <div style={{ marginBottom: 16 }}><Notice tone="warn">This is not the current run for its version. Its results are kept for the record only.</Notice></div>}
      <Tabs
        items={[
          { to: `/runs/${run.id}`, label: "Findings", icon: ListChecks, end: true },
          { to: `/runs/${run.id}/impact`, label: "Reporting impact", icon: BarChart3 },
          { to: `/versions/${run.dataset_version_id}/review`, label: "Review and publish", icon: Gavel },
        ]}
      />
    </>
  );
}

type SeverityFilter = "ALL" | "BLOCKING" | "WARNING" | "INFO";
type StatusFilter = "ALL" | "OPEN" | "WAIVER_REQUESTED" | "WAIVED" | "NONE";

export function RunPage() {
  const { runId = "" } = useParams();
  const navigate = useNavigate();
  const { run, version } = useRun(runId);
  const findings = useLoad(() => api.get<Page<Finding>>(`/runs/${runId}/findings`), [runId]);
  const issues = useLoad(() => api.get<Page<Issue>>(`/runs/${runId}/issues`), [runId]);
  const config = useLoad(() => api.get<{ rules: RuleConfig[] }>(`/datasets/${DATASET}/config`), []);
  const [query, setQuery] = useState("");
  const [severity, setSeverity] = useState<SeverityFilter>("ALL");
  const [status, setStatus] = useState<StatusFilter>("ALL");

  const issueOf = useMemo(() => new Map(issues.data?.items.map((i) => [i.finding_id, i])), [issues.data]);
  const all = findings.data?.items ?? [];
  const rows = all.filter((f) => {
    if (severity !== "ALL" && f.severity !== severity) return false;
    const issue = issueOf.get(f.id);
    if (status === "NONE" && issue) return false;
    if (status !== "ALL" && status !== "NONE" && issue?.state !== status) return false;
    const q = query.trim().toLowerCase();
    return !q || f.rule_id.toLowerCase().includes(q) || f.message.toLowerCase().includes(q) || f.columns.some((c) => c.includes(q));
  });

  const r = run.data;
  if (run.loading && !r) return <PageLoading />;
  if (!r) return <ErrorNotice error={run.error} />;

  const failed = new Set(all.map((f) => f.rule_id));
  const skipped = new Set(r.not_evaluated.map((n) => n.rule_id));
  const passed = (config.data?.rules ?? []).filter((rule) => !failed.has(rule.id) && !skipped.has(rule.id));
  const counts = r.finding_counts ?? { BLOCKING: 0, WARNING: 0, INFO: 0 };
  const segments = [
    { key: "passed", label: "Passed", value: passed.length, color: "var(--ok)" },
    { key: "blocking", label: "Blocking", value: counts.BLOCKING, color: "var(--viz-confirmed)" },
    { key: "warning", label: "Warnings", value: counts.WARNING, color: "var(--viz-potential)" },
    { key: "info", label: "Information", value: counts.INFO, color: "var(--info)" },
    { key: "skipped", label: "Not evaluated", value: r.not_evaluated.length, color: "#c4cede" },
  ];
  const by = (s: string) => all.filter((f) => f.severity === s).length;

  return (
    <>
      <RunHeader run={r} version={version} title="Validation results" />
      <div className="stack">
        <Card flush>
          <div className="stat-strip">
            <div>
              <div className="label"><i style={{ background: "var(--ok)" }} />Rules passed</div>
              <div className="value">{config.data ? passed.length : "—"}<span className="faint" style={{ fontSize: 14, fontWeight: 500 }}> / {config.data?.rules.length ?? "—"}</span></div>
            </div>
            <div>
              <div className="label"><i style={{ background: "var(--viz-confirmed)" }} />Blocking</div>
              <div className={`value ${counts.BLOCKING ? "text-danger" : ""}`}>{counts.BLOCKING}</div>
            </div>
            <div>
              <div className="label"><i style={{ background: "var(--viz-potential)" }} />Warnings</div>
              <div className={`value ${counts.WARNING ? "text-warn" : ""}`}>{counts.WARNING}</div>
            </div>
            <div>
              <div className="label"><i style={{ background: "#c4cede" }} />Not evaluated</div>
              <div className="value">{r.not_evaluated.length}</div>
            </div>
          </div>
          <div style={{ padding: "0 18px 16px" }} className="stack-sm">
            <StackBar segments={segments} label="Rule outcomes" />
            <Legend items={segments.filter((s) => s.value > 0).map((s) => ({ label: `${s.label} ${s.value}`, color: s.color }))} />
          </div>
        </Card>

        {all.length === 0 && findings.data && <Notice tone="ok" title="No findings">Every rule that could be evaluated passed.</Notice>}

        <Card
          title="Findings"
          subtitle="Blocking findings must be fixed at source or waived. Warnings are acknowledged at approval."
          flush
        >
          <div className="table-tools">
            <label className="search">
              <Search aria-hidden />
              <span className="sr-only">Search findings</span>
              <input className="input" type="search" placeholder="Search rule, message or column" value={query} onChange={(e) => setQuery(e.target.value)} />
            </label>
            <Segmented<SeverityFilter>
              label="Severity"
              value={severity}
              onChange={setSeverity}
              options={[
                { value: "ALL", label: "All", count: all.length },
                { value: "BLOCKING", label: "Blocking", count: by("BLOCKING") },
                { value: "WARNING", label: "Warnings", count: by("WARNING") },
                { value: "INFO", label: "Info", count: by("INFO") },
              ]}
            />
            <select className="select" style={{ width: 190 }} aria-label="Issue status" value={status} onChange={(e) => setStatus(e.target.value as StatusFilter)}>
              <option value="ALL">Any status</option>
              <option value="OPEN">Open</option>
              <option value="WAIVER_REQUESTED">Waiver requested</option>
              <option value="WAIVED">Waived</option>
              <option value="NONE">No issue (info)</option>
            </select>
          </div>
          {findings.loading && !findings.data && <Skeleton lines={6} />}
          <ErrorNotice error={findings.error} />
          {findings.data && (
            <DataTable
              rows={rows}
              rowKey={(f) => f.id}
              onRowClick={(f) => navigate(`/findings/${f.id}`)}
              caption="Findings"
              empty={
                <Empty icon={all.length ? SearchX : CheckCircle2} title={all.length ? "No findings match" : "No findings"}>
                  {all.length ? "Change the search or filters." : "Every rule passed."}
                </Empty>
              }
              columns={[
                { key: "severity", header: "Severity", className: "nowrap", render: (f) => <Severity value={f.severity} />, sort: (f) => ({ BLOCKING: 0, WARNING: 1, INFO: 2 })[f.severity] },
                {
                  key: "rule",
                  header: "Rule",
                  className: "nowrap",
                  sort: (f) => f.rule_id,
                  render: (f) => (
                    <div>
                      <Link to={`/findings/${f.id}`} className="rule-id" onClick={(e) => e.stopPropagation()}>{f.rule_id}</Link>
                      <div className="faint" style={{ fontSize: 12 }}>{f.rule_type.replace(/_/g, " ")} · {f.table}</div>
                    </div>
                  ),
                },
                { key: "message", header: "Finding", className: "wrap", render: (f) => f.message },
                { key: "records", header: "Records", align: "right", sort: (f) => f.failing_count, render: (f) => <strong className="num">{count(f.failing_count)}</strong> },
                { key: "waivable", header: "Waivable", className: "nowrap", render: (f) => (f.severity !== "BLOCKING" ? <span className="faint">n/a</span> : f.waivable ? "Yes" : <span className="text-danger">No, fix at source</span>) },
                { key: "status", header: "Status", className: "nowrap", render: (f) => { const i = issueOf.get(f.id); return i ? <IssueState state={i.state} severity={i.severity} /> : <span className="faint">—</span>; } },
              ]}
            />
          )}
        </Card>

        {r.not_evaluated.length > 0 && (
          <Card title={`Not evaluated (${r.not_evaluated.length})`} subtitle="Rules that need a required column the upload does not have." flush>
            <DataTable
              rows={r.not_evaluated}
              rowKey={(n) => n.rule_id}
              columns={[
                { key: "id", header: "Rule", className: "nowrap", render: (n) => <span className="rule-id">{n.rule_id}</span> },
                { key: "missing", header: "Missing columns", className: "wrap", render: (n) => <code>{n.missing_columns.join(", ")}</code> },
              ]}
            />
          </Card>
        )}
        <Card title={`Passed checks (${passed.length})`} subtitle="Rules that found no problem in this version." flush>
            {config.loading && !config.data ? (
              <Skeleton lines={4} />
            ) : passed.length === 0 ? (
              <Empty compact title="No rule passed" />
            ) : (
              <DataTable
                rows={passed}
                rowKey={(p) => p.id}
                columns={[
                  { key: "ok", header: "", width: 28, render: () => <CheckCircle2 width={15} height={15} className="text-ok" aria-label="Passed" /> },
                  { key: "id", header: "Rule", className: "nowrap", render: (p) => <span className="rule-id">{p.id}</span> },
                  { key: "name", header: "Check", className: "wrap", render: (p) => p.name },
                  { key: "sev", header: "Severity if failed", className: "nowrap", render: (p) => <Severity value={p.severity} /> },
                ]}
              />
            )}
          </Card>
      </div>
    </>
  );
}
