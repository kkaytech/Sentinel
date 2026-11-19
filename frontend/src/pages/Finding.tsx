import { Download, Rows3, Table2 } from "lucide-react";
import { useState } from "react";
import { useParams } from "react-router-dom";
import { api, type Finding, type FindingImpact, type FindingRecord, type Page, type Run, type Version } from "../api";
import { Pager } from "../components/DataTable";
import { Badge, Card, Empty, ErrorNotice, Money, Notice, PageHeader, PageLoading, Severity, Skeleton } from "../components/ui";
import { CATEGORY_LABELS, KPI_NAMES, count, useLoad } from "../lib";
import { IssuePanel } from "./IssuePanel";

const PAGE_SIZE = 50;

function RecordsTable({ records, grouped, order }: { records: FindingRecord[]; grouped: boolean; order: string[] }) {
  // Failing columns first, then the file's columns in contract order, then anything else.
  const failing = records[0]?.failing_columns ?? [];
  const present = new Set(records.flatMap((r) => Object.keys(r.cells)));
  const columns = Array.from(new Set([...failing, ...order, ...present])).filter((c) => present.has(c));
  const rows = grouped ? [...records].sort((a, b) => (a.group_no ?? 1e9) - (b.group_no ?? 1e9) || a.row_num - b.row_num) : records;
  return (
    <div className="table-wrap">
      <table className="table">
        <thead>
          <tr>
            <th className="right">Row</th>
            <th>Record key</th>
            {grouped && <th>Group</th>}
            {columns.map((c) => (
              <th key={c}>{c}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={`${r.row_num}-${r.group_no ?? ""}`}>
              <td className="right faint num">{r.row_num}</td>
              <td className="nowrap"><code>{r.record_key}</code></td>
              {grouped && (
                <td className="nowrap">
                  {r.group_no === null ? "—" : <><span className="num">#{r.group_no}</span> {r.is_canonical ? <Badge tone="neutral">canonical</Badge> : <Badge tone="danger">duplicate</Badge>}</>}
                </td>
              )}
              {columns.map((c) => {
                const fail = r.failing_columns.includes(c);
                const value = r.cells[c];
                return (
                  <td key={c} className={`nowrap ${fail ? "cell-fail" : ""}`}>
                    {value === null || value === undefined ? <span className="faint">∅</span> : value === "" ? <span className="faint">(empty)</span> : value}
                    {fail && <span className="sr-only"> (failing)</span>}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function FindingPage() {
  const { findingId = "" } = useParams();
  const [offset, setOffset] = useState(0);
  const finding = useLoad(() => api.get<Finding>(`/findings/${findingId}`), [findingId]);
  const runId = finding.data?.run_id;
  const run = useLoad(() => (runId ? api.get<Run>(`/runs/${runId}`) : Promise.resolve(null)), [runId]);
  const versionId = run.data?.dataset_version_id;
  const version = useLoad(() => (versionId ? api.get<Version>(`/versions/${versionId}`) : Promise.resolve(null)), [versionId]);
  const impact = useLoad(() => api.get<FindingImpact>(`/findings/${findingId}/impact`), [findingId]);
  const records = useLoad(() => api.get<Page<FindingRecord>>(`/findings/${findingId}/records?limit=${PAGE_SIZE}&offset=${offset}`), [findingId, offset]);

  const f = finding.data;
  if (finding.loading && !f) return <PageLoading />;
  if (!f) return <ErrorNotice error={finding.error} />;
  const grouped = records.data?.items.some((r) => r.group_no !== null) ?? false;
  const effects = (impact.data?.kpi_effects ?? []).filter((e) => e.direction !== "NONE");
  const share = f.evaluated_count ? (f.failing_count / f.evaluated_count) * 100 : 0;

  return (
    <>
      <PageHeader
        crumbs={[
          { label: "Reporting periods", to: "/periods" },
          ...(run.data ? [{ label: run.data.period, to: `/periods/${run.data.period}` }, { label: version.data?.label ?? "Version", to: `/versions/${run.data.dataset_version_id}` }, { label: "Findings", to: `/runs/${f.run_id}` }] : []),
          { label: f.rule_id },
        ]}
        title={<span className="mono" style={{ fontSize: "inherit" }}>{f.rule_id}</span>}
        badge={<Severity value={f.severity} />}
        subtitle={f.message}
        actions={
          <a className="btn" href={api.url(`/findings/${f.id}/records.csv`)}>
            <Download aria-hidden />
            Export records (CSV)
          </a>
        }
      />
      <div className="stack">
        <div className="split">
          <div className="stack">
            <Card title="Evidence">
              <dl className="props">
                <dt>Rule type</dt>
                <dd>{f.rule_type.replace(/_/g, " ")}</dd>
                <dt>Table and columns</dt>
                <dd className="row" style={{ gap: 6 }}>
                  <code>{f.table}</code>
                  {f.columns.map((c) => <Badge key={c} tone="danger">{c}</Badge>)}
                </dd>
                <dt>Failing records</dt>
                <dd>
                  <strong className="num">{count(f.failing_count)}</strong> of {count(f.evaluated_count)} evaluated
                  <span className="faint"> ({share < 0.1 && share > 0 ? "<0.1" : share.toFixed(1)}%)</span>
                  {f.truncated && <div className="text-warn">The stored record list is capped; the count is exact.</div>}
                </dd>
                <dt>Waivable</dt>
                <dd>{f.severity !== "BLOCKING" ? "Not applicable" : f.waivable ? "Yes, with an approver's decision" : <span className="text-danger">No, must be fixed at source</span>}</dd>
                {typeof f.details.groups === "number" && (
                  <>
                    <dt>Duplicate groups</dt>
                    <dd>{String(f.details.groups)}</dd>
                  </>
                )}
              </dl>
            </Card>
            <Card title="Financial impact" subtitle="Per currency. Never combined across currencies." flush>
              {impact.loading && !impact.data && <Skeleton lines={3} />}
              {impact.data && impact.data.figures.length === 0 && <Empty compact title="No monetary figure">This rule describes data quality, not a financial misstatement.</Empty>}
              {impact.data && impact.data.figures.length > 0 && (
                <div className="table-wrap">
                  <table className="table">
                    <thead>
                      <tr>
                        <th>Category</th>
                        <th className="right">Amount</th>
                        <th className="right">Records</th>
                        <th>Basis</th>
                      </tr>
                    </thead>
                    <tbody>
                      {impact.data.figures.map((g, n) => (
                        <tr key={n}>
                          <td className="nowrap"><Badge tone={g.category === "CONFIRMED_DISCREPANCY" ? "danger" : "warn"}>{CATEGORY_LABELS[g.category] ?? g.category}</Badge></td>
                          <td className="right strong"><Money amount={g.amount} currency={g.currency} /></td>
                          <td className="right">{g.record_count}{Number(g.inputs.unquantifiable_count ?? 0) > 0 && <div className="faint" style={{ fontSize: 12 }}>{String(g.inputs.unquantifiable_count)} not valued</div>}</td>
                          <td className="wrap muted" style={{ fontSize: 12.5 }}>{g.assumption}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </Card>
          </div>
          <IssuePanel runId={f.run_id} findingId={f.id} />
        </div>

        <Card
          title={<span className="row" style={{ gap: 8 }}><Rows3 width={16} height={16} aria-hidden />Affected records</span>}
          subtitle={grouped ? "In each group the lowest row is kept as canonical. This is a reporting convention, not a claim about which record is genuine." : "Failing cells are highlighted and labelled."}
          actions={records.data ? <Badge tone="neutral">{count(records.data.total)} records</Badge> : undefined}
          flush
        >
          <ErrorNotice error={records.error} />
          {records.loading && !records.data && <Skeleton lines={6} />}
          {records.data && records.data.total === 0 && <Empty icon={Table2} title="No individual records">This finding concerns the file's columns, not its rows.</Empty>}
          {records.data && records.data.items.length > 0 && (
            <>
              <RecordsTable records={records.data.items} grouped={grouped} order={version.data?.columns[f.table] ?? []} />
              <Pager offset={offset} size={PAGE_SIZE} total={records.data.total} onChange={setOffset} />
            </>
          )}
        </Card>

        {effects.length > 0 && (
          <Card title="Estimated reporting impact" subtitle="How this issue changes the KPIs a report on this version would show." flush>
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>KPI</th>
                    <th>Supplier</th>
                    <th className="right">Adjusted value</th>
                    <th className="right">Change</th>
                    <th>Direction</th>
                    <th>Assumption</th>
                  </tr>
                </thead>
                <tbody>
                  {effects.slice(0, 40).map((e, n) => (
                    <tr key={n}>
                      <td className="nowrap"><strong>{e.kpi_id}</strong> <span className="muted">{KPI_NAMES[e.kpi_id]}</span></td>
                      <td className="nowrap">{e.supplier_id ? <code>{e.supplier_id}</code> : <span className="faint">All</span>}</td>
                      <td className="right">{e.kpi_id === "KPI-03" ? `${Number(e.value).toLocaleString("en-GB")} invoices` : <Money amount={e.value} currency={e.currency} />}</td>
                      <td className="right nowrap">{e.delta_abs ? (e.kpi_id === "KPI-03" ? Number(e.delta_abs) : <Money amount={e.delta_abs} currency={e.currency} />) : "—"}{e.delta_pct && <span className="faint"> {e.delta_pct}%</span>}</td>
                      <td className="nowrap"><Badge tone={e.direction === "OVERSTATED" ? "danger" : e.direction === "UNDERSTATED" ? "warn" : "neutral"}>{e.direction?.toLowerCase()}</Badge></td>
                      <td className="wrap muted" style={{ fontSize: 12.5 }}>{e.assumption}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {effects.length > 40 && <div className="table-foot">Showing 40 of {effects.length} changed values.</div>}
          </Card>
        )}
        {impact.data && effects.length === 0 && impact.data.figures.length > 0 && <Notice tone="info">This issue does not change any KPI value: the affected records are outside what the KPIs count.</Notice>}
      </div>
    </>
  );
}
