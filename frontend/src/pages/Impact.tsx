import { CircleDollarSign, Info, Scale, TrendingUp, UserX } from "lucide-react";
import { useMemo } from "react";
import { Link, useParams } from "react-router-dom";
import { DATASET, api, type Finding, type FindingImpact, type Page, type RunImpact } from "../api";
import { BarList, CompareBars, Donut, Legend } from "../components/Charts";
import { DataTable } from "../components/DataTable";
import { Badge, Card, Empty, Kpi, LoadError, Money, PageLoading, Segmented, Skeleton } from "../components/ui";
import { CATEGORY_LABELS, CATEGORY_NOTES, KPI_NAMES, compact, groupDigits, plural, useLoad, useUrlState } from "../lib";
import { RunHeader, useRun } from "./Run";

const CATEGORY_COLORS: Record<string, string> = {
  CONFIRMED_DISCREPANCY: "var(--viz-confirmed)",
  POTENTIAL_EXPOSURE: "var(--viz-potential)",
};

interface RuleImpact {
  finding: Finding;
  impact: FindingImpact;
}

async function loadRuleImpacts(runId: string): Promise<RuleImpact[]> {
  const findings = await api.get<Page<Finding>>(`/runs/${runId}/findings`);
  const impacts = await Promise.all(findings.items.map((f) => api.get<FindingImpact>(`/findings/${f.id}/impact`)));
  return findings.items.map((finding, n) => ({ finding, impact: impacts[n] })).filter((x) => x.impact.figures.length > 0);
}

const money = (amount: string, currency: string) => <Money amount={amount} currency={currency} compactValue={compact(amount)} />;

export function ImpactPage() {
  const { runId = "" } = useParams();
  const { run, version } = useRun(runId);
  const impact = useLoad(() => api.get<RunImpact>(`/runs/${runId}/impact`), [runId]);
  const rules = useLoad(() => loadRuleImpacts(runId), [runId]);
  const [view, setView] = useUrlState({ ccy: "" });
  const picked = view.ccy || null;
  const setPicked = (ccy: string) => setView({ ccy });
  const config = useLoad(() => api.get<{ contract_version: { contract: { reference_lists: Record<string, string[] | string> } } }>(`/datasets/${DATASET}/config`), []);
  const allowed = config.data?.contract_version.contract.reference_lists.currencies;
  const invalid = (c: string) => Array.isArray(allowed) && !allowed.includes(c);

  // Currencies in order of reported spend; the largest is shown first.
  const currencies = useMemo(() => {
    const spend = new Map<string, number>();
    for (const k of impact.data?.kpis ?? []) if (k.kpi_id === "KPI-01") spend.set(k.currency, Number(k.as_reported));
    for (const t of impact.data?.totals ?? []) if (!spend.has(t.currency)) spend.set(t.currency, 0);
    return [...spend.entries()].sort((a, b) => b[1] - a[1]).map(([c]) => c);
  }, [impact.data]);
  const currency = picked && currencies.includes(picked) ? picked : (currencies[0] ?? "");

  if ((run.loading && !run.data) || (impact.loading && !impact.data)) return <PageLoading />;
  if (!run.data) return <LoadError error={run.error} onRetry={run.reload} />;
  const data = impact.data;
  if (!data) return <LoadError error={impact.error} onRetry={impact.reload} />;

  const total = (category: string) => data.totals.find((t) => t.category === category && t.currency === currency);
  const confirmed = total("CONFIRMED_DISCREPANCY");
  const potential = total("POTENTIAL_EXPOSURE");
  const kpi = (id: string) => data.kpis.find((k) => k.kpi_id === id && k.currency === currency);
  const spend = kpi("KPI-01");
  const unattributed = kpi("KPI-04");

  const byRule = (rules.data ?? [])
    .flatMap(({ finding, impact: fi }) =>
      fi.figures
        .filter((g) => g.currency === currency && g.amount !== null && Number(g.amount) !== 0)
        .map((g) => ({ finding, figure: g })),
    )
    .sort((a, b) => Math.abs(Number(b.figure.amount)) - Math.abs(Number(a.figure.amount)));

  const suppliers = data.supplier_ranking.filter((s) => s.currency === currency);
  const compareRows = ["KPI-01", "KPI-03", "KPI-04"]
    .map((id) => kpi(id))
    .filter((k): k is NonNullable<typeof k> => !!k);
  const anyImpact = data.totals.length > 0;

  return (
    <>
      <RunHeader run={run.data} version={version} title="Reporting impact" />
      <div className="stack">
        {currencies.length === 0 ? (
          <Card>
            <Empty icon={CircleDollarSign} title="No financial data">No invoices fall inside the reporting period, so there is nothing to quantify.</Empty>
          </Card>
        ) : (
          <>
            <div className="row" style={{ justifyContent: "space-between" }}>
              <Segmented label="Currency" value={currency} onChange={setPicked} options={currencies.map((c) => ({ value: c, label: invalid(c) ? `${c} (invalid)` : c }))} />
              <span className="muted" style={{ fontSize: 14 }}>
                Figures are per currency. Sentinel never converts or combines currencies.
              </span>
            </div>
            <div className="kpis" style={{ marginBottom: 0 }}>
              <Kpi
                label="Confirmed discrepancy"
                icon={Scale}
                tone={confirmed && Number(confirmed.amount) ? "danger" : "ok"}
                value={confirmed ? money(confirmed.amount, currency) : money("0.00", currency)}
                hint={confirmed ? `${plural(confirmed.record_count, "record")} proven misstated` : "Nothing proven misstated"}
              />
              <Kpi
                label="Potential exposure"
                icon={CircleDollarSign}
                tone={potential && Number(potential.amount) ? "warn" : undefined}
                value={potential ? money(potential.amount, currency) : money("0.00", currency)}
                hint={potential ? `${plural(potential.record_count, "record")}${potential.unquantifiable_count ? `, ${potential.unquantifiable_count} not valued` : ""}` : "No uncertain records"}
              />
              <Kpi
                label="Total spend overstated by"
                icon={TrendingUp}
                tone={spend?.direction === "OVERSTATED" ? "danger" : "ok"}
                value={spend?.delta_abs && spend.direction !== "NONE" ? money(spend.delta_abs, currency) : <span className="text-ok">No change</span>}
                hint={spend ? <>KPI-01 {spend.delta_pct && spend.direction !== "NONE" ? `${spend.delta_pct}% ` : ""}after removing confirmed duplicates</> : "No spend in this currency"}
              />
              <Kpi
                label="Unattributed spend"
                icon={UserX}
                tone={unattributed && Number(unattributed.as_reported) ? "warn" : undefined}
                value={unattributed ? money(unattributed.as_reported, currency) : "—"}
                hint="KPI-04: no known supplier"
              />
            </div>

            <div className="split-wide">
              <Card title="Impact by rule" subtitle={`Each rule's figure in ${currency}. A record can appear under more than one rule.`}>
                {rules.loading && !rules.data ? (
                  <Skeleton lines={5} />
                ) : byRule.length === 0 ? (
                  <Empty compact title={`No quantified impact in ${currency}`} />
                ) : (
                  <div className="stack">
                    <BarList
                      data={byRule.map(({ finding, figure }) => ({
                        key: `${finding.id}-${figure.category}`,
                        label: <Link to={`/findings/${finding.id}`} className="rule-id" title={finding.message}>{finding.rule_id}</Link>,
                        value: Number(figure.amount),
                        color: CATEGORY_COLORS[figure.category],
                        display: <span className="money">{compact(figure.amount ?? "0")}</span>,
                        title: `${CATEGORY_LABELS[figure.category]}: ${groupDigits(figure.amount ?? "0")} ${currency}`,
                      }))}
                    />
                    <Legend items={Object.entries(CATEGORY_COLORS).map(([k, color]) => ({ label: CATEGORY_LABELS[k], color }))} />
                  </div>
                )}
              </Card>
              <Card title="Version totals" subtitle="Each record counts once. Confirmed takes precedence over potential.">
                {!anyImpact || (!confirmed && !potential) ? (
                  <Empty compact title={`No financial impact in ${currency}`} />
                ) : (
                  <div className="stack" style={{ alignItems: "center" }}>
                    <Donut
                      size={156}
                      label={`records affected`}
                      value={(confirmed?.record_count ?? 0) + (potential?.record_count ?? 0)}
                      segments={[
                        { key: "c", label: "Confirmed discrepancy", value: confirmed?.record_count ?? 0, color: CATEGORY_COLORS.CONFIRMED_DISCREPANCY },
                        { key: "p", label: "Potential exposure", value: potential?.record_count ?? 0, color: CATEGORY_COLORS.POTENTIAL_EXPOSURE },
                      ]}
                    />
                    <div className="stack-sm" style={{ width: "100%" }}>
                      {[confirmed, potential].filter(Boolean).map((t) => (
                        <div key={t!.category} className="row" style={{ justifyContent: "space-between", fontSize: 14, flexWrap: "nowrap" }}>
                          <Legend items={[{ label: CATEGORY_LABELS[t!.category], color: CATEGORY_COLORS[t!.category] }]} />
                          <span className="strong"><Money amount={t!.amount} currency={currency} /></span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </Card>
            </div>

            <Card
              title="KPIs: as reported versus fully adjusted"
              subtitle="Fully adjusted removes every confirmed duplicate copy. Other issues have no safe adjustment, so they are explained rather than corrected."
              actions={<Legend items={[{ label: "As reported", color: "var(--viz-reported)" }, { label: "Fully adjusted", color: "var(--viz-adjusted)" }]} />}
            >
              {compareRows.length === 0 ? (
                <Empty compact title={`No KPI values in ${currency}`} />
              ) : (
                <CompareBars
                  data={compareRows.map((k) => {
                    const isCount = k.kpi_id === "KPI-03";
                    const label = (v: string) => (isCount ? `${Number(v).toLocaleString("en-GB")} invoices` : <Money amount={v} currency={currency} compactValue={compact(v)} />);
                    return {
                      key: k.kpi_id,
                      name: <>{k.kpi_id} · {KPI_NAMES[k.kpi_id]}</>,
                      meta: (
                        <span className="row" style={{ gap: 6 }}>
                          <Badge tone={k.direction === "OVERSTATED" ? "danger" : k.direction === "UNDERSTATED" ? "warn" : "neutral"}>{k.direction === "NONE" ? "no change" : k.direction?.toLowerCase()}</Badge>
                          {k.delta_pct && k.direction !== "NONE" && <span>{k.delta_pct}%</span>}
                        </span>
                      ),
                      reported: Number(k.as_reported),
                      adjusted: Number(k.fully_adjusted),
                      reportedLabel: label(k.as_reported),
                      adjustedLabel: label(k.fully_adjusted),
                    };
                  })}
                />
              )}
            </Card>

            <div className="split-wide">
              <Card
                title="Suppliers whose spend changes"
                subtitle={`KPI-02 in ${currency}: spend removed by the fully adjusted view, largest first.`}
                actions={<Badge tone="neutral">{data.supplier_ranking_total} in all currencies</Badge>}
              >
                {suppliers.length === 0 ? (
                  <Empty compact title={`No supplier's spend changes in ${currency}`} />
                ) : (
                  <BarList
                    color="var(--viz-confirmed)"
                    data={suppliers.slice(0, 12).map((s) => ({
                      key: `${s.currency}-${s.supplier_id}`,
                      label: <code>{s.supplier_id}</code>,
                      value: Number(s.delta_abs ?? 0),
                      display: (
                        <span>
                          <span className="money">{compact(s.delta_abs ?? "0")}</span>
                          <span className="faint" style={{ marginLeft: 6, fontWeight: 400 }}>{s.delta_pct}%</span>
                        </span>
                      ),
                      title: `${s.supplier_id}: ${groupDigits(s.as_reported)} as reported, ${groupDigits(s.fully_adjusted)} adjusted`,
                    }))}
                  />
                )}
              </Card>
              <Card title="How to read these figures" flush>
                {Object.entries(CATEGORY_NOTES).map(([k, note]) => (
                  <div className="insight" key={k}>
                    <span style={{ width: 10, height: 10, borderRadius: 3, background: CATEGORY_COLORS[k], marginTop: 5, flex: "none" }} aria-hidden />
                    <div>
                      <strong>{CATEGORY_LABELS[k]}.</strong> {note}
                    </div>
                  </div>
                ))}
                <div className="insight">
                  <span style={{ width: 10, height: 10, borderRadius: 3, background: "var(--viz-estimated)", marginTop: 5, flex: "none" }} aria-hidden />
                  <div>
                    <strong>Estimated reporting impact.</strong> The change in a KPI under a stated assumption. Duplicate copies are removed by convention, keeping the first occurrence.
                  </div>
                </div>
                <div className="insight">
                  <Info className="faint" aria-hidden />
                  <div className="muted">Figures use exact decimal arithmetic. Records whose amount cannot be parsed are counted but never valued.</div>
                </div>
              </Card>
            </div>

            <Card title="All currencies" subtitle="Version totals and KPI-01 for every currency code found in this version. Invalid codes are reported by INV_CODE_CURRENCY." flush>
              <DataTable
                rows={currencies}
                rowKey={(c) => c}
                onRowClick={(c) => setPicked(c)}
                columns={[
                  { key: "ccy", header: "Currency", className: "strong", render: (c) => <span className="row" style={{ gap: 6 }}>{c}{invalid(c) && <Badge tone="warn">invalid code</Badge>}{c === currency && <Badge tone="accent">Shown</Badge>}</span> },
                  { key: "spend", header: "Spend as reported", align: "right", render: (c) => { const k = data.kpis.find((x) => x.kpi_id === "KPI-01" && x.currency === c); return k ? <Money amount={k.as_reported} currency={c} /> : "—"; } },
                  { key: "conf", header: "Confirmed discrepancy", align: "right", render: (c) => { const t = data.totals.find((x) => x.category === "CONFIRMED_DISCREPANCY" && x.currency === c); return t ? <Money amount={t.amount} currency={c} /> : <span className="faint">—</span>; } },
                  { key: "pot", header: "Potential exposure", align: "right", render: (c) => { const t = data.totals.find((x) => x.category === "POTENTIAL_EXPOSURE" && x.currency === c); return t ? <Money amount={t.amount} currency={c} /> : <span className="faint">—</span>; } },
                  { key: "dir", header: "KPI-01", className: "nowrap", render: (c) => { const k = data.kpis.find((x) => x.kpi_id === "KPI-01" && x.currency === c); return k ? <Badge tone={k.direction === "OVERSTATED" ? "danger" : "neutral"}>{k.direction === "NONE" ? "no change" : k.direction?.toLowerCase()}</Badge> : "—"; } },
                ]}
              />
            </Card>
          </>
        )}
      </div>
    </>
  );
}
