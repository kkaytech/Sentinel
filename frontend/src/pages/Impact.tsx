import { useParams } from "react-router-dom";
import { api, type RunImpact } from "../api";
import { CATEGORY_LABELS, Card, Empty, ErrorBox, Loading, Money, useLoad } from "../ui";
import { RunHeader, useRun } from "./Run";

const KPI_NAMES: Record<string, string> = {
  "KPI-01": "Total invoiced spend",
  "KPI-02": "Spend by supplier",
  "KPI-03": "Invoice count",
  "KPI-04": "Unattributed spend",
};

const CATEGORY_NOTES: Record<string, string> = {
  CONFIRMED_DISCREPANCY: "A misstatement the dataset alone proves, with an exact value.",
  POTENTIAL_EXPOSURE: "The value of records whose correct treatment cannot be determined.",
};

export function ImpactPage() {
  const { runId = "" } = useParams();
  const { run, version } = useRun(runId);
  const impact = useLoad(() => api.get<RunImpact>(`/runs/${runId}/impact`), [runId]);
  const data = impact.data;
  return (
    <>
      <ErrorBox error={run.error ?? impact.error} />
      {run.data && <RunHeader run={run.data} version={version} />}
      {impact.loading && !data && <Loading />}
      {data && (
        <>
          <Card title="Version totals">
            <p className="muted" style={{ marginTop: 0 }}>
              Each record is counted once per category. A confirmed discrepancy takes precedence over potential exposure. Totals are per currency; there is no conversion and no combined total.
            </p>
            {data.totals.length === 0 ? (
              <Empty>No financial impact was found.</Empty>
            ) : (
              <table>
                <thead>
                  <tr>
                    <th>Category</th>
                    <th className="num">Amount</th>
                    <th className="num">Records</th>
                    <th className="num">Value not quantifiable</th>
                    <th>Meaning</th>
                  </tr>
                </thead>
                <tbody>
                  {data.totals.map((t) => (
                    <tr key={t.category + t.currency}>
                      <td>
                        <strong>{CATEGORY_LABELS[t.category] ?? t.category}</strong>
                      </td>
                      <td className="num">
                        <Money amount={t.amount} currency={t.currency} />
                      </td>
                      <td className="num">{t.record_count}</td>
                      <td className="num">{t.unquantifiable_count}</td>
                      <td className="muted">{CATEGORY_NOTES[t.category]}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Card>
          <Card title="Estimated reporting impact on KPIs">
            <p className="muted" style={{ marginTop: 0 }}>
              "As reported" is what a report built on this version would show. "Fully adjusted" removes every confirmed duplicate copy.
            </p>
            {data.kpis.length === 0 ? (
              <Empty>No KPI values: no invoices fall inside the reporting period.</Empty>
            ) : (
              <table>
                <thead>
                  <tr>
                    <th>KPI</th>
                    <th className="num">As reported</th>
                    <th className="num">Fully adjusted</th>
                    <th className="num">Delta</th>
                    <th>Direction</th>
                    <th>Assumption</th>
                  </tr>
                </thead>
                <tbody>
                  {data.kpis.map((k) => {
                    const count = k.kpi_id === "KPI-03";
                    const show = (value: string) => (count ? `${Number(value).toLocaleString()} (${k.currency})` : <Money amount={value} currency={k.currency} />);
                    return (
                      <tr key={k.kpi_id + k.currency}>
                        <td>
                          {k.kpi_id} <span className="muted">{KPI_NAMES[k.kpi_id]}</span>
                        </td>
                        <td className="num">{show(k.as_reported)}</td>
                        <td className="num">{show(k.fully_adjusted)}</td>
                        <td className="num">
                          {k.delta_abs ? (count ? Number(k.delta_abs) : <Money amount={k.delta_abs} currency={k.currency} />) : "—"}
                          {k.delta_pct ? ` (${k.delta_pct}%)` : ""}
                        </td>
                        <td>{k.direction === "NONE" ? "No change" : k.direction}</td>
                        <td className="muted">{k.assumption}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </Card>
          <Card title={`Suppliers whose spend changes (${data.supplier_ranking_total})`}>
            {data.supplier_ranking.length === 0 ? (
              <Empty>No supplier's spend changes after adjustment.</Empty>
            ) : (
              <>
                <table>
                  <thead>
                    <tr>
                      <th>Supplier</th>
                      <th className="num">As reported</th>
                      <th className="num">Fully adjusted</th>
                      <th className="num">Delta</th>
                      <th>Direction</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.supplier_ranking.map((k) => (
                      <tr key={k.currency + k.supplier_id}>
                        <td className="mono">{k.supplier_id}</td>
                        <td className="num">
                          <Money amount={k.as_reported} currency={k.currency} />
                        </td>
                        <td className="num">
                          <Money amount={k.fully_adjusted} currency={k.currency} />
                        </td>
                        <td className="num">
                          <Money amount={k.delta_abs} currency={k.currency} />
                          {k.delta_pct ? ` (${k.delta_pct}%)` : ""}
                        </td>
                        <td>{k.direction}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {data.supplier_ranking_total > data.supplier_ranking.length && (
                  <p className="muted">Showing the {data.supplier_ranking.length} largest of {data.supplier_ranking_total}.</p>
                )}
              </>
            )}
          </Card>
        </>
      )}
    </>
  );
}
