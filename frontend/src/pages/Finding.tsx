import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, type Finding, type FindingImpact, type FindingRecord, type Page, type Run } from "../api";
import { CATEGORY_LABELS, Card, Empty, ErrorBox, Loading, Money, Severity, useLoad } from "../ui";

const PAGE_SIZE = 50;

export function FindingPage() {
  const { findingId = "" } = useParams();
  const [offset, setOffset] = useState(0);
  const finding = useLoad(() => api.get<Finding>(`/findings/${findingId}`), [findingId]);
  const runId = finding.data?.run_id;
  const run = useLoad(() => (runId ? api.get<Run>(`/runs/${runId}`) : Promise.resolve(null)), [runId]);
  const impact = useLoad(() => api.get<FindingImpact>(`/findings/${findingId}/impact`), [findingId]);
  const records = useLoad(
    () => api.get<Page<FindingRecord>>(`/findings/${findingId}/records?limit=${PAGE_SIZE}&offset=${offset}`),
    [findingId, offset],
  );
  const f = finding.data;
  const columns = records.data?.items.length
    ? Array.from(new Set(records.data.items.flatMap((r) => Object.keys(r.cells))))
    : [];
  const grouped = records.data?.items.some((r) => r.group_no !== null) ?? false;

  return (
    <>
      <ErrorBox error={finding.error ?? records.error ?? impact.error} />
      {finding.loading && !f && <Loading />}
      {f && (
        <>
          <div className="crumbs">
            <Link to="/periods">Periods</Link>
            {run.data && (
              <>
                {" / "}
                <Link to={`/versions/${run.data.dataset_version_id}`}>version</Link>
                {" / "}
                <Link to={`/runs/${f.run_id}`}>findings</Link>
              </>
            )}{" "}
            / {f.rule_id}
          </div>
          <div className="page-head">
            <div>
              <h1>
                <span className="mono">{f.rule_id}</span> <Severity value={f.severity} />
              </h1>
              <p>{f.message}</p>
            </div>
            <div className="actions">
              <a className="button" href={api.url(`/findings/${f.id}/records.csv`)}>
                Export records (CSV)
              </a>
            </div>
          </div>
          <Card title="Evidence">
            <dl className="facts">
              <dt>Rule type</dt>
              <dd>{f.rule_type}</dd>
              <dt>Table and columns</dt>
              <dd>
                {f.table}: {f.columns.join(", ")}
              </dd>
              <dt>Failing records</dt>
              <dd>
                {f.failing_count.toLocaleString()} of {f.evaluated_count.toLocaleString()} evaluated
                {f.truncated && " — the stored key list is truncated; the count is exact"}
              </dd>
              <dt>Waivable</dt>
              <dd>{f.severity !== "BLOCKING" ? "Not applicable (not blocking)" : f.waivable ? "Yes" : "No — must be fixed at source"}</dd>
            </dl>
          </Card>

          <Card title="Financial impact">
            {impact.data && impact.data.figures.length === 0 && <Empty>This rule carries no monetary figure.</Empty>}
            {impact.data && impact.data.figures.length > 0 && (
              <table>
                <thead>
                  <tr>
                    <th>Category</th>
                    <th className="num">Amount</th>
                    <th className="num">Records</th>
                    <th className="num">Not quantifiable</th>
                    <th>Formula</th>
                    <th>Assumption</th>
                  </tr>
                </thead>
                <tbody>
                  {impact.data.figures.map((g, n) => (
                    <tr key={n}>
                      <td>{CATEGORY_LABELS[g.category] ?? g.category}</td>
                      <td className="num">
                        <Money amount={g.amount} currency={g.currency} />
                      </td>
                      <td className="num">{g.record_count}</td>
                      <td className="num">{String(g.inputs.unquantifiable_count ?? 0)}</td>
                      <td className="mono">{g.formula_id}</td>
                      <td>{g.assumption}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            {impact.data && impact.data.kpi_effects.length > 0 && (
              <>
                <h3>Estimated reporting impact</h3>
                <table>
                  <thead>
                    <tr>
                      <th>KPI</th>
                      <th>Supplier</th>
                      <th className="num">Adjusted value</th>
                      <th className="num">Delta</th>
                      <th>Direction</th>
                      <th>Assumption</th>
                    </tr>
                  </thead>
                  <tbody>
                    {impact.data.kpi_effects.filter((e) => e.direction !== "NONE").slice(0, 60).map((e, n) => (
                      <tr key={n}>
                        <td>{e.kpi_id}</td>
                        <td>{e.supplier_id ?? "—"}</td>
                        <td className="num">
                          <Money amount={e.value} currency={e.currency} />
                        </td>
                        <td className="num">{e.delta_abs ? <Money amount={e.delta_abs} currency={e.currency} /> : "—"}{e.delta_pct ? ` (${e.delta_pct}%)` : ""}</td>
                        <td>{e.direction ?? "—"}</td>
                        <td>{e.assumption}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <p className="muted">KPI values this issue does not change are omitted. At most 60 rows are shown.</p>
              </>
            )}
          </Card>

          <Card title={`Affected records (${records.data?.total.toLocaleString() ?? "…"})`}>
            {grouped && (
              <p className="muted" style={{ marginTop: 0 }}>
                In each group the record with the lowest row number is kept as canonical. This is a reporting convention, not a claim about which record is genuine.
              </p>
            )}
            {records.loading && !records.data && <Loading />}
            {records.data && records.data.total === 0 && <Empty>This finding concerns the file's columns, not individual records.</Empty>}
            {records.data && records.data.items.length > 0 && (
              <>
                <div className="scroll">
                  <table>
                    <thead>
                      <tr>
                        <th className="num">Row</th>
                        <th>Record key</th>
                        {grouped && <th>Group</th>}
                        {columns.map((c) => (
                          <th key={c}>{c}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {records.data.items.map((r) => (
                        <tr key={r.row_num}>
                          <td className="num">{r.row_num}</td>
                          <td className="mono">{r.record_key}</td>
                          {grouped && <td>{r.group_no === null ? "—" : `${r.group_no} ${r.is_canonical ? "(canonical)" : "(duplicate)"}`}</td>}
                          {columns.map((c) => (
                            <td key={c} className={r.failing_columns.includes(c) ? "fail" : undefined}>
                              {r.cells[c] === null || r.cells[c] === undefined ? <span className="muted">∅</span> : r.cells[c] === "" ? <span className="muted">(empty)</span> : r.cells[c]}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div className="pager">
                  <span>
                    {offset + 1}–{offset + records.data.items.length} of {records.data.total.toLocaleString()}
                  </span>
                  <button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>
                    Previous
                  </button>
                  <button disabled={offset + PAGE_SIZE >= records.data.total} onClick={() => setOffset(offset + PAGE_SIZE)}>
                    Next
                  </button>
                </div>
              </>
            )}
          </Card>
        </>
      )}
    </>
  );
}
