import {
  AlertOctagon,
  ArrowRight,
  CalendarRange,
  CheckCircle2,
  CircleDot,
  FileCheck2,
  FileUp,
  Gavel,
  Layers,
  Lightbulb,
  Scale,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  TrendingUp,
  type LucideIcon,
} from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { DATASET, api, type AuditEvent, type Page, type PeriodRow, type Publication, type ReviewSummary } from "../api";
import { useAuth } from "../auth";
import { BarList, ColumnChart, Donut, Funnel, Gauge, Legend, Sparkline } from "../components/Charts";
import { DataTable, type Column } from "../components/DataTable";
import { Badge, Card, CountUp, Empty, Kpi, LoadError, Money, Segmented, StateBadge } from "../components/ui";
import { ago, compact, count, groupDigits, plural, useLoad, useUrlState } from "../lib";

interface PeriodHealth {
  row: PeriodRow;
  summary: ReviewSummary | null;
}

const QUIET_EVENTS = new Set(["LOGIN_SUCCEEDED", "LOGIN_FAILED", "LOGOUT", "VALIDATION_RUN_STARTED", "CONFIG_RELOAD_UNCHANGED"]);

async function loadOverview() {
  const periods = await api.get<Page<PeriodRow>>(`/datasets/${DATASET}/periods`);
  const [summaries, publications, config, first] = await Promise.all([
    Promise.all(periods.items.map((p) => (p.current_version ? api.get<ReviewSummary>(`/versions/${p.current_version.id}/review-summary`).catch(() => null) : Promise.resolve(null)))),
    api.get<Page<Publication>>("/publications"),
    api.get<{ rules: unknown[] }>(`/datasets/${DATASET}/config`),
    api.get<Page<AuditEvent>>("/audit/events?limit=1"),
  ]);
  // The audit list is chronological; read the last page for the most recent events.
  const offset = Math.max(0, first.total - 40);
  const recent = await api.get<Page<AuditEvent>>(`/audit/events?limit=40&offset=${offset}`);
  return {
    health: periods.items.map((row, n) => ({ row, summary: summaries[n] })) as PeriodHealth[],
    publications: publications.items,
    ruleCount: config.rules.length,
    activity: [...recent.items.filter((e) => !QUIET_EVENTS.has(e.event_type))].reverse().slice(0, 7),
  };
}

// ---- Stages -------------------------------------------------------------------------------
const STAGES = ["Uploaded", "Validated", "Unblocked", "Approved", "Published"];

function stagesDone(h: PeriodHealth): { done: number; blocked: boolean } {
  const s = h.summary;
  if (!h.row.current_version || !s) return { done: 0, blocked: false };
  if (h.row.derived_state === "PUBLISHED") return { done: 5, blocked: false };
  const passed = (id: string) => s.eligibility.checks.find((c) => c.id === id)?.passed ?? false;
  let done = 1;
  if (passed("E4")) done = 2;
  if (done === 2 && passed("E5")) done = 3;
  if (done === 3 && passed("E6")) done = 4;
  return { done, blocked: done === 2 && s.blocking_non_waivable_count > 0 };
}

type Stage = "published" | "ready" | "review" | "blocked" | "progress" | "pending";
const STAGE_META: Record<Stage, { label: string; color: string }> = {
  published: { label: "Published", color: "#22d3ee" },
  ready: { label: "Ready to publish", color: "#34d399" },
  review: { label: "Awaiting approval", color: "#a78bfa" },
  progress: { label: "Resolving issues", color: "#fbbf24" },
  blocked: { label: "Needs corrected data", color: "#fb7185" },
  pending: { label: "Not validated", color: "#64748b" },
};

function stageOf(h: PeriodHealth): Stage {
  const s = h.summary;
  if (h.row.derived_state === "PUBLISHED") return "published";
  if (!h.row.current_version || !s?.current_run_id) return "pending";
  if (s.eligibility.eligible) return "ready";
  if (s.blocking_non_waivable_count > 0) return "blocked";
  if (s.request?.status === "OPEN") return "review";
  return "progress";
}

function Pipeline({ health }: { health: PeriodHealth }) {
  const { done, blocked } = stagesDone(health);
  return (
    <div className="pipeline" role="img" aria-label={`${done} of ${STAGES.length} stages complete`}>
      {STAGES.map((stage, n) => {
        const state = n < done ? "done" : n === done ? (blocked ? "blocked" : "current") : "";
        return (
          <div className="pipeline-step" key={stage} title={`${stage}${n < done ? ": complete" : n === done ? ": next" : ""}`}>
            {n > 0 && <span className={`pipeline-line ${n <= done ? "done" : ""}`} />}
            <span className={`pipeline-dot ${state}`}>{n < done ? <CheckCircle2 /> : state === "blocked" ? <AlertOctagon /> : <CircleDot />}</span>
          </div>
        );
      })}
    </div>
  );
}

function nextStep(h: PeriodHealth): { text: string; to: string } {
  const v = h.row.current_version;
  const s = h.summary;
  if (!v) return { text: "Upload data", to: `/periods?period=${h.row.period}#upload` };
  const review = `/versions/${v.id}/review`;
  if (h.row.derived_state === "PUBLISHED") return { text: "View publication", to: v.publication_ref ? `/publications/${v.publication_ref}` : review };
  if (!s?.current_run_id) return { text: "Run validation", to: `/versions/${v.id}` };
  if (s.blocking_non_waivable_count > 0) return { text: "Corrected upload needed", to: `/runs/${s.current_run_id}` };
  if (s.blocking_unwaived_count > 0) return { text: `Resolve ${plural(s.blocking_unwaived_count, "blocker")}`, to: `/runs/${s.current_run_id}` };
  if (s.eligibility.eligible) return { text: "Ready to publish", to: review };
  if (s.request?.status === "OPEN") return { text: "Awaiting approval", to: review };
  return { text: "Submit for review", to: review };
}

// ---- Audit event wording (also used by the audit trail) ------------------------------------------
const EVENTS: Record<string, { text: string; icon: LucideIcon; tone?: string }> = {
  VERSION_CREATED: { text: "Dataset version uploaded", icon: FileUp, tone: "accent" },
  VERSION_SUPERSEDED: { text: "Earlier version superseded", icon: FileUp },
  INGESTION_FAILED: { text: "Upload rejected", icon: AlertOctagon, tone: "danger" },
  VALIDATION_RUN_STARTED: { text: "Validation started", icon: ShieldCheck },
  VALIDATION_RUN_COMPLETED: { text: "Validation completed", icon: ShieldCheck, tone: "accent" },
  VALIDATION_RUN_FAILED: { text: "Validation failed", icon: AlertOctagon, tone: "danger" },
  ISSUES_OPENED: { text: "Issues opened", icon: ShieldAlert, tone: "warn" },
  WAIVER_REQUESTED: { text: "Waiver requested", icon: Gavel, tone: "warn" },
  WAIVER_GRANTED: { text: "Waiver granted", icon: Gavel, tone: "ok" },
  WAIVER_DENIED: { text: "Waiver denied", icon: Gavel, tone: "danger" },
  ISSUE_NOTE_ADDED: { text: "Investigation note added", icon: Sparkles },
  REVIEW_SUBMITTED: { text: "Submitted for review", icon: Gavel, tone: "accent" },
  REVIEW_APPROVED: { text: "Review approved", icon: CheckCircle2, tone: "ok" },
  REVIEW_REJECTED: { text: "Review rejected", icon: AlertOctagon, tone: "danger" },
  DATASET_PUBLISHED: { text: "Dataset published", icon: FileCheck2, tone: "ok" },
  PUBLICATION_VERIFIED: { text: "Publication verified", icon: ShieldCheck, tone: "ok" },
  PUBLICATION_REFUSED: { text: "Publication refused", icon: AlertOctagon, tone: "danger" },
  LOGIN_SUCCEEDED: { text: "Signed in", icon: CircleDot },
  LOGOUT: { text: "Signed out", icon: CircleDot },
  CONFIG_ACTIVATED: { text: "Rule configuration activated", icon: ShieldCheck },
};

export function describeEvent(e: AuditEvent): { text: string; icon: LucideIcon; tone?: string; detail?: string } {
  const known = EVENTS[e.event_type];
  const payload = e.payload as Record<string, unknown>;
  const detail = typeof payload.label === "string" ? payload.label : typeof payload.rule_id === "string" ? payload.rule_id : e.entity_type === "publication" ? e.entity_id : undefined;
  if (known) return { ...known, detail };
  const text = e.event_type.charAt(0) + e.event_type.slice(1).toLowerCase().replace(/_/g, " ");
  return { text, icon: CircleDot, detail };
}

// ---- Helpers ------------------------------------------------------------------------------
function amountOf(h: PeriodHealth, category: string, currency: string | undefined): string {
  return h.summary?.live?.impact_totals.find((t) => t.category === category && t.currency === currency)?.amount ?? "0.00";
}

function totalOf(h: PeriodHealth, category: string, currency: string | undefined) {
  return h.summary?.live?.impact_totals.find((t) => t.category === category && t.currency === currency) ?? null;
}

const runOf = (h: PeriodHealth | null | undefined) => h?.summary?.current_run_id ?? null;

// The period that contributes most (or least) to a figure, for drill-down from the KPI cards.
function extreme(rows: PeriodHealth[], value: (h: PeriodHealth) => number, pick: "max" | "min"): PeriodHealth | null {
  let best: PeriodHealth | null = null;
  for (const h of rows) {
    if (!runOf(h)) continue;
    if (!best || (pick === "max" ? value(h) > value(best) : value(h) < value(best))) best = h;
  }
  return best;
}

function OverviewSkeleton() {
  return (
    <div className="ov-skeleton" aria-busy="true" aria-label="Loading the overview">
      <div className="hero glass" style={{ minHeight: 190 }}>
        <div className="stack-sm">
          <div className="skeleton" style={{ height: 12, width: 260 }} />
          <div className="skeleton" style={{ height: 30, width: "min(420px, 80%)", marginTop: 6 }} />
          <div className="skeleton" style={{ height: 14, width: "min(560px, 90%)" }} />
        </div>
      </div>
      <div className="row" style={{ marginBottom: 18, gap: 8 }}>
        {[90, 80, 80, 80].map((w, n) => (
          <div key={n} className="skeleton" style={{ height: 36, width: w, borderRadius: 999 }} />
        ))}
      </div>
      <div className="kpis">
        {[0, 1, 2, 3].map((n) => (
          <div key={n} className="kpi">
            <div className="skeleton" style={{ height: 12, width: "55%" }} />
            <div className="skeleton" style={{ height: 28, width: "45%", marginTop: 14 }} />
            <div className="skeleton" style={{ height: 40, width: "100%", marginTop: 18 }} />
          </div>
        ))}
      </div>
      <div className="split-wide">
        <div className="card" style={{ minHeight: 320 }} />
        <div className="card" style={{ minHeight: 320 }} />
      </div>
    </div>
  );
}

// Exact sum of decimal strings, in integer minor units.
function sumAmounts(amounts: string[]): string {
  const cents = amounts.reduce((n, a) => n + BigInt(a.replace("-", "").replace(".", "")) * (a.startsWith("-") ? -1n : 1n), 0n);
  const negative = cents < 0n;
  const abs = (negative ? -cents : cents).toString().padStart(3, "0");
  return `${negative ? "-" : ""}${abs.slice(0, -2)}.${abs.slice(-2)}`;
}

function greeting(): string {
  const hour = new Date().getHours();
  return hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening";
}

// ---- Page ---------------------------------------------------------------------------------
export function OverviewPage() {
  const { session, has } = useAuth();
  const { data, error, loading, reload } = useLoad(loadOverview, []);
  // The focused period and currency live in the address, so Back returns to the same view.
  const [view, setView] = useUrlState({ period: "", ccy: "" });
  const focus = view.period || null;
  const picked = view.ccy || null;
  const setFocus = (period: string | null) => setView({ period: period ?? "" });
  const setPicked = (ccy: string) => setView({ ccy });
  const [mixHover, setMixHover] = useState<string | null>(null);

  const chronological = useMemo(() => [...(data?.health ?? [])].sort((a, b) => a.row.period.localeCompare(b.row.period)), [data]);
  const currencies = useMemo(() => {
    const totals = new Map<string, number>();
    for (const h of chronological) for (const t of h.summary?.live?.impact_totals ?? []) totals.set(t.currency, (totals.get(t.currency) ?? 0) + Number(t.amount));
    return [...totals.entries()].sort((a, b) => b[1] - a[1]).map(([c]) => c);
  }, [chronological]);

  if (loading && !data) return <OverviewSkeleton />;
  if (!data) return <LoadError error={error} onRetry={reload} title="The overview could not be loaded" />;

  const currency = picked && currencies.includes(picked) ? picked : currencies[0];
  const focused = focus ? chronological.find((h) => h.row.period === focus) ?? null : null;
  const scope = focused ? [focused] : chronological;
  const focusIndex = focused ? chronological.indexOf(focused) : undefined;
  const ruleCount = data.ruleCount;

  // Figures for the current focus: one period, or every period.
  const blockingOf = (h: PeriodHealth) => h.summary?.blocking_unwaived_count ?? 0;
  const issuesOf = (h: PeriodHealth) => h.summary?.issues ?? [];
  const passingOf = (h: PeriodHealth) => (h.summary?.current_run_id ? Math.max(ruleCount - issuesOf(h).length, 0) : null);
  const validated = scope.filter((h) => passingOf(h) !== null);
  const passing = validated.reduce((n, h) => n + (passingOf(h) ?? 0), 0);
  const possible = validated.length * ruleCount;
  const healthPct = possible ? Math.round((passing / possible) * 100) : 0;
  const blockers = scope.filter((h) => h.row.derived_state !== "PUBLISHED").reduce((n, h) => n + blockingOf(h), 0);
  const confirmed = sumAmounts(scope.map((h) => amountOf(h, "CONFIRMED_DISCREPANCY", currency)));
  const potential = sumAmounts(scope.map((h) => amountOf(h, "POTENTIAL_EXPOSURE", currency)));
  const issues = scope.flatMap(issuesOf);
  const warnings = issues.filter((i) => i.severity === "WARNING").length;
  const published = data.health.filter((h) => h.row.derived_state === "PUBLISHED").length;
  const awaiting = data.health.filter((h) => h.summary?.request?.status === "OPEN" && h.row.derived_state !== "PUBLISHED").length;
  const needsAttention = data.health.filter((h) => ["blocked", "progress"].includes(stageOf(h))).length;
  const invoices = data.health.reduce((n, h) => n + (h.row.current_version?.row_counts.invoices ?? 0), 0);

  const funnel = STAGES.map((label, i) => {
    const reached = chronological.filter((h) => stagesDone(h).done > i);
    return { label, count: reached.length, periods: reached.map((h) => h.row.period) };
  });
  const funnelHighlight = focused ? Math.min(stagesDone(focused).done, STAGES.length - 1) : null;

  const mix = [
    { key: "open", label: "Blocking, open", value: issues.filter((i) => i.severity === "BLOCKING" && i.state === "OPEN").length, color: "#fb7185" },
    { key: "requested", label: "Waiver requested", value: issues.filter((i) => i.state === "WAIVER_REQUESTED").length, color: "#fbbf24" },
    { key: "waived", label: "Waived", value: issues.filter((i) => i.state === "WAIVED").length, color: "#22d3ee" },
    { key: "warnings", label: "Warnings", value: warnings, color: "#a78bfa" },
  ];

  const recurring = new Map<string, { rule: string; periods: number; records: number; blocking: boolean }>();
  for (const h of scope)
    for (const i of issuesOf(h)) {
      const r = recurring.get(i.rule_id) ?? { rule: i.rule_id, periods: 0, records: 0, blocking: i.severity === "BLOCKING" };
      r.periods += 1;
      r.records += i.failing_count ?? 0;
      recurring.set(i.rule_id, r);
    }
  const topRules = [...recurring.values()].sort((a, b) => b.records - a.records || b.periods - a.periods).slice(0, 6);

  const insights: { icon: LucideIcon; tone: string; text: ReactNode }[] = [];
  for (const h of scope.filter((x) => x.row.derived_state !== "PUBLISHED")) {
    const s = h.summary;
    if (!s) continue;
    if (s.blocking_non_waivable_count > 0) insights.push({ icon: AlertOctagon, tone: "text-danger", text: <><strong>{h.row.period}</strong> has {plural(s.blocking_non_waivable_count, "blocking issue")} that cannot be waived. Only a corrected upload can make it publishable.</> });
    else if (s.blocking_unwaived_count > 0) insights.push({ icon: ShieldAlert, tone: "text-warn", text: <><strong>{h.row.period}</strong> has {plural(s.blocking_unwaived_count, "waivable blocking issue")} without a granted waiver.</> });
    if (s.request?.status === "OPEN") insights.push({ icon: Gavel, tone: "text-warn", text: <><strong>{h.row.period}</strong> was submitted for review {ago(s.request.submitted_at)} and is waiting for an approver.</> });
    if (s.eligibility.eligible) insights.push({ icon: CheckCircle2, tone: "text-ok", text: <><strong>{h.row.period}</strong> passes every publication check and can be published.</> });
    const c = s.live?.impact_totals.filter((t) => t.category === "CONFIRMED_DISCREPANCY").sort((a, b) => Number(b.amount) - Number(a.amount))[0];
    if (c && Number(c.amount) > 0) insights.push({ icon: Lightbulb, tone: "text-danger", text: <><strong>{h.row.period}</strong> overstates spend by a confirmed <Money amount={c.amount} currency={c.currency} /> across {plural(c.record_count, "record")}.</> });
  }

  const columns: Column<PeriodHealth>[] = [
    { key: "period", header: "Period", className: "strong nowrap", sort: (h) => h.row.period, render: (h) => <Link to={`/periods/${h.row.period}`} onClick={(e) => e.stopPropagation()}>{h.row.period}</Link> },
    { key: "state", header: "Status", className: "nowrap", render: (h) => <StateBadge state={h.row.derived_state} /> },
    { key: "pipeline", header: "Progress", render: (h) => <Pipeline health={h} /> },
    { key: "blocking", header: "Blocking", align: "right", sort: (h) => blockingOf(h), render: (h) => (h.summary ? <span className={blockingOf(h) ? "text-danger" : ""}>{blockingOf(h)}</span> : "—") },
    {
      key: "next",
      header: "Next step",
      className: "nowrap",
      render: (h) => {
        const n = nextStep(h);
        return (
          <Link to={n.to} onClick={(e) => e.stopPropagation()} className="row" style={{ gap: 4, flexWrap: "nowrap" }}>
            {n.text}
            <ArrowRight width={14} height={14} aria-hidden />
          </Link>
        );
      },
    },
  ];

  const labels = chronological.map((h) => h.row.period);
  const spark = (values: number[], color: string, label: string, format?: (v: number) => string) => (
    <Sparkline values={values} color={color} highlight={focusIndex} label={label} labels={labels} format={format} />
  );
  const money = (v: number) => `${compact(v)} ${currency ?? ""}`;
  const healthOf = (h: PeriodHealth) => (passingOf(h) === null ? 0 : Math.round(((passingOf(h) ?? 0) / ruleCount) * 100));
  const unpublished = chronological.filter((h) => h.row.derived_state !== "PUBLISHED");

  // Each KPI opens the figures behind it: the focused period, or the period that drives the figure.
  const blockTarget = focused ?? (blockers ? extreme(unpublished, blockingOf, "max") : null);
  const blockLink = runOf(blockTarget) ? { to: `/runs/${runOf(blockTarget)}`, action: focused ? "View findings" : `Most in ${blockTarget?.row.period}` } : { to: "/periods", action: "View periods" };
  const impactLink = (category: string) => {
    const target = focused ?? extreme(chronological, (h) => Number(amountOf(h, category, currency)), "max");
    if (!runOf(target)) return { to: "/periods", action: "View periods" };
    return { to: `/runs/${runOf(target)}/impact`, action: focused ? "View impact" : `Largest in ${target?.row.period}` };
  };
  const healthTarget = focused ?? extreme(chronological, healthOf, "min");
  const healthLink = runOf(healthTarget) ? { to: `/runs/${runOf(healthTarget)}`, action: focused ? "View findings" : `Weakest: ${healthTarget?.row.period}` } : { to: "/periods", action: "View periods" };
  const swap = (key: string, node: ReactNode) => (
    <span key={key} className="swap">
      {node}
    </span>
  );
  const scopeLabel = focused ? `Period ${focused.row.period}` : "All periods";
  const name = session?.user.display_name ?? "";

  return (
    <>
      <section className="hero glass">
        <span className="hero-sheen" aria-hidden />
        <div>
          <span className="eyebrow">
            <Sparkles width={14} height={14} aria-hidden />
            Supplier invoices · {new Date().toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" })}
          </span>
          <h1>
            {greeting()}, <span className="gradient-text">{name}</span>
          </h1>
          <p className="hero-sub">
            {data.health.length === 0 ? (
              "No reporting periods yet. Upload a month of supplier and invoice files to begin."
            ) : (
              <>
                {plural(data.health.length, "reporting period")} tracked. {needsAttention ? `${plural(needsAttention, "period")} ${needsAttention === 1 ? "needs" : "need"} attention` : "Nothing is blocked"},{" "}
                {awaiting ? `${awaiting} awaiting approval` : "none awaiting approval"}, and {published} published.
              </>
            )}
          </p>
          <div className="row" style={{ marginTop: 16, gap: 10 }}>
            {has("ANALYST") && (
              <Link className="btn primary" to="/periods#upload">
                <FileUp aria-hidden />
                Upload data
              </Link>
            )}
            <Link className="btn" to="/publications">
              <FileCheck2 aria-hidden />
              Publications
            </Link>
          </div>
        </div>
        <div className="hero-stats">
          <div className="hero-stat">
            <div className="k"><Layers width={14} height={14} aria-hidden />Invoices in scope</div>
            <div className="v"><CountUp value={invoices} /></div>
          </div>
          <div className="hero-stat">
            <div className="k"><ShieldCheck width={14} height={14} aria-hidden />Rules active</div>
            <div className="v"><CountUp value={ruleCount} /></div>
          </div>
          <div className="hero-stat">
            <div className="k"><FileCheck2 width={14} height={14} aria-hidden />Published</div>
            <div className="v">
              <CountUp value={published} />
              <span className="faint" style={{ fontSize: 14, fontWeight: 500 }}> / {data.health.length}</span>
            </div>
          </div>
        </div>
      </section>

      {data.health.length === 0 ? (
        <Card>
          <Empty icon={CalendarRange} title="No reporting periods yet" action={has("ANALYST") ? <Link className="btn primary" to="/periods#upload">Upload the first period</Link> : undefined}>
            Upload a month of supplier and invoice files to begin.
          </Empty>
        </Card>
      ) : (
        <>
          <div className="period-strip" role="group" aria-label="Focus period">
            <span className="label">Focus</span>
            <button type="button" className="chip" aria-pressed={!focused} onClick={() => setFocus(null)}>
              All periods
            </button>
            {chronological.map((h) => (
              <button key={h.row.period} type="button" className="chip" aria-pressed={focus === h.row.period} onClick={() => setFocus(h.row.period)}>
                <span className="sdot" style={{ background: STAGE_META[stageOf(h)].color, boxShadow: `0 0 8px ${STAGE_META[stageOf(h)].color}` }} aria-hidden />
                {h.row.period}
                <span className="sr-only"> ({STAGE_META[stageOf(h)].label})</span>
              </button>
            ))}
            <span className="spacer" />
            {currencies.length > 1 && <Segmented label="Reporting currency" value={currency ?? ""} onChange={setPicked} options={currencies.slice(0, 4).map((c) => ({ value: c, label: c }))} />}
          </div>

          <div className="kpis stagger">
            <Kpi
              label="Open blocking issues"
              icon={ShieldAlert}
              tone={blockers ? "danger" : "ok"}
              value={<CountUp value={blockers} />}
              hint={swap(scopeLabel, focused ? scopeLabel : blockers ? "Across unpublished periods" : "Nothing is blocking publication")}
              spark={spark(chronological.map(blockingOf), "#fb7185", "Blocking issues")}
              {...blockLink}
            />
            <Kpi
              label="Confirmed discrepancy"
              icon={Scale}
              tone={Number(confirmed) ? "danger" : "ok"}
              value={<span title={`${groupDigits(confirmed)} ${currency ?? ""}`}><CountUp value={Number(confirmed)} format={compact} /><small>{currency}</small></span>}
              hint={swap(scopeLabel, `${scopeLabel} · proven misstatement`)}
              spark={spark(chronological.map((h) => Number(amountOf(h, "CONFIRMED_DISCREPANCY", currency))), "#f472b6", "Confirmed discrepancy", money)}
              {...impactLink("CONFIRMED_DISCREPANCY")}
            />
            <Kpi
              label="Potential exposure"
              icon={TrendingUp}
              tone={Number(potential) ? "warn" : undefined}
              value={<span title={`${groupDigits(potential)} ${currency ?? ""}`}><CountUp value={Number(potential)} format={compact} /><small>{currency}</small></span>}
              hint={swap(scopeLabel, `${scopeLabel} · uncertain treatment`)}
              spark={spark(chronological.map((h) => Number(amountOf(h, "POTENTIAL_EXPOSURE", currency))), "#fbbf24", "Potential exposure", money)}
              {...impactLink("POTENTIAL_EXPOSURE")}
            />
            <Kpi
              label="Validation health"
              icon={ShieldCheck}
              tone="accent"
              value={<><CountUp value={healthPct} />%</>}
              hint={swap(scopeLabel, possible ? `${count(passing)} of ${count(possible)} rule checks clean` : "Not validated yet")}
              spark={spark(chronological.map(healthOf), "#2dd4bf", "Validation health", (v) => `${v}%`)}
              {...healthLink}
            />
          </div>

          <div className="split-wide stagger" style={{ marginBottom: 18 }}>
            <Card
              title="Financial impact by period"
              subtitle={currency ? swap(currency, `${currency}. Hover for the figures, select a period to focus the dashboard.`) : "No financial impact recorded."}
              actions={<Legend items={[{ label: "Confirmed discrepancy", color: "var(--viz-confirmed)" }, { label: "Potential exposure", color: "var(--viz-potential)" }]} />}
            >
              {!currency ? (
                <Empty compact title="No financial impact in any period" />
              ) : (
                <ColumnChart
                  selected={focus}
                  onSelect={(key) => setFocus(focus === key ? null : key)}
                  ticks={(v) => compact(v)}
                  data={chronological.map((h) => {
                    const records = (category: string) => {
                      const n = totalOf(h, category, currency)?.record_count ?? 0;
                      return plural(n, "record");
                    };
                    const all = sumAmounts(chronological.map((x) => amountOf(x, "CONFIRMED_DISCREPANCY", currency)));
                    const share = Number(all) ? ((Number(amountOf(h, "CONFIRMED_DISCREPANCY", currency)) / Number(all)) * 100).toFixed(1) : "0.0";
                    return {
                      key: h.row.period,
                      label: h.row.period,
                      values: [
                        { label: "Confirmed discrepancy", value: Number(amountOf(h, "CONFIRMED_DISCREPANCY", currency)), color: "linear-gradient(180deg, #fb7185, #e11d48)", display: `${groupDigits(amountOf(h, "CONFIRMED_DISCREPANCY", currency))} ${currency}`, detail: records("CONFIRMED_DISCREPANCY") },
                        { label: "Potential exposure", value: Number(amountOf(h, "POTENTIAL_EXPOSURE", currency)), color: "linear-gradient(180deg, #fcd34d, #f59e0b)", display: `${groupDigits(amountOf(h, "POTENTIAL_EXPOSURE", currency))} ${currency}`, detail: records("POTENTIAL_EXPOSURE") },
                      ],
                      note: `${share}% of all confirmed discrepancy · ${STAGE_META[stageOf(h)].label} · ${focus === h.row.period ? "click to show all periods" : "click to focus"}`,
                    };
                  })}
                />
              )}
            </Card>
            <Card title="Validation health" subtitle={swap(scopeLabel, `${scopeLabel} · current validation runs`)}>
              {validated.length === 0 ? (
                <Empty compact title="Not validated yet" icon={ShieldCheck} />
              ) : (
                <div className="stack" style={{ alignItems: "center", gap: 14 }}>
                  <Gauge value={passing} max={possible} label="rule checks clean" display={<><CountUp value={healthPct} />%</>} tone={healthPct >= 90 ? "ok" : healthPct >= 70 ? "cool" : "danger"} />
                  <div className="grid-3" style={{ width: "100%", gap: 8 }}>
                    {[
                      { k: "Blocking", v: issues.filter((i) => i.severity === "BLOCKING" && i.state !== "WAIVED").length, c: "var(--danger)" },
                      { k: "Warnings", v: warnings, c: "var(--orchid)" },
                      { k: "Waived", v: issues.filter((i) => i.state === "WAIVED").length, c: "var(--cyan)" },
                    ].map((s) => (
                      <div key={s.k} className="hero-stat" style={{ minWidth: 0, textAlign: "center", padding: "10px 8px" }}>
                        <div className="v" style={{ color: s.c }}><CountUp value={s.v} /></div>
                        <div className="k" style={{ justifyContent: "center" }}>{s.k}</div>
                      </div>
                    ))}
                  </div>
                  {focused && (
                    <Link to={nextStep(focused).to} className="btn block">
                      {nextStep(focused).text}
                      <ArrowRight aria-hidden />
                    </Link>
                  )}
                </div>
              )}
            </Card>
          </div>

          <div className="split-wide stagger" style={{ marginBottom: 18 }}>
            <Card title="Publication pipeline" subtitle={swap(scopeLabel, focused ? `Every period, with ${focused.row.period}'s next stage highlighted` : "How far every period has progressed toward an immutable publication")}>
              <Funnel stages={funnel} highlight={funnelHighlight} />
            </Card>
            <Card title="Issue mix" subtitle={swap(scopeLabel, `${scopeLabel} · by state. Hover to read a segment.`)}>
              {issues.length === 0 ? (
                <Empty compact icon={CheckCircle2} title="No open issues">{focused ? "This period validated clean." : "Every period validated clean."}</Empty>
              ) : (
                <div className="row" style={{ gap: 20, flexWrap: "nowrap", justifyContent: "center" }}>
                  <Donut segments={mix} value={<CountUp value={issues.length} />} label="issues" size={150} thickness={16} active={mixHover} onActive={setMixHover} />
                  <div className="stack-sm" style={{ flex: 1, minWidth: 0, gap: 2 }} onMouseLeave={() => setMixHover(null)}>
                    {mix.map((m) => (
                      <div key={m.key} className={`mix-row ${mixHover === m.key ? "on" : ""}`} onMouseEnter={() => setMixHover(m.key)}>
                        <Legend items={[{ label: m.label, color: m.color }]} />
                        <strong className="num">
                          <CountUp value={m.value} />
                          <span className="faint" style={{ fontWeight: 500, fontSize: 12.5, marginLeft: 6 }}>{issues.length ? Math.round((m.value / issues.length) * 100) : 0}%</span>
                        </strong>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </Card>
          </div>

          <div className="split-wide stagger" style={{ marginBottom: 18 }}>
            <Card title="Reporting periods" subtitle="Select a row to focus the dashboard. Open a period from its name." flush>
              <DataTable
                columns={columns}
                rows={data.health}
                rowKey={(h) => h.row.period}
                onRowClick={(h) => setFocus(focus === h.row.period ? null : h.row.period)}
                rowClassName={(h) => (h.row.period === focus ? "selected" : undefined)}
                initialSort={{ key: "period", dir: "desc" }}
              />
            </Card>
            <Card title="Needs attention" subtitle={swap(scopeLabel, scopeLabel)} flush>
              {insights.length === 0 ? (
                <Empty compact icon={CheckCircle2} title="Nothing needs attention" />
              ) : (
                <div>
                  {insights.slice(0, 6).map((i, n) => (
                    <div className="insight" key={n}>
                      <i.icon className={i.tone} aria-hidden />
                      <div>{i.text}</div>
                    </div>
                  ))}
                </div>
              )}
            </Card>
          </div>

          <div className="grid-2 stagger">
            <Card title="Largest recurring issues" subtitle={swap(scopeLabel, `${scopeLabel} · records affected, and the periods each rule fails in`)}>
              {topRules.length === 0 ? (
                <Empty compact title="No issues" />
              ) : (
                <BarList
                  data={topRules.map((r) => ({
                    key: r.rule,
                    label: <span className="rule-id" style={{ color: r.blocking ? "var(--danger)" : "var(--ink)" }}>{r.rule}</span>,
                    value: r.records,
                    color: r.blocking ? "var(--viz-confirmed)" : "var(--viz-reported)",
                    display: <span>{plural(r.records, "record")} <span className="faint" style={{ fontWeight: 400 }}>· {plural(r.periods, "period")}</span></span>,
                    title: `${r.rule}: ${r.records} records in ${r.periods} period(s)`,
                  }))}
                />
              )}
            </Card>
            <Card title="Recent activity" subtitle="From the append-only audit trail" actions={<Link to="/audit" className="btn sm ghost">View all</Link>} flush>
              {data.activity.length === 0 ? (
                <Empty compact title="No activity yet" />
              ) : (
                <div className="activity">
                  {data.activity.map((e) => {
                    const d = describeEvent(e);
                    return (
                      <div className="activity-item" key={e.id}>
                        <span className={`activity-icon ${d.tone ?? ""}`} aria-hidden>
                          <d.icon />
                        </span>
                        <div className="activity-text">
                          <strong>{d.text}</strong>
                          {d.detail && <span className="muted"> · {d.detail}</span>}
                          <div className="faint" style={{ fontSize: 13 }}>
                            {e.actor_kind === "SYSTEM" ? "System" : "User"} · {e.entity_type.replace(/_/g, " ")}
                          </div>
                        </div>
                        <span className="tl-time nowrap">{ago(e.occurred_at)}</span>
                      </div>
                    );
                  })}
                </div>
              )}
            </Card>
          </div>
          <p className="faint" style={{ marginTop: 18, fontSize: 13 }}>
            <Badge tone="neutral">{plural(data.publications.length, "publication")}</Badge> Figures are recomputed from each period's current validation run and never combined across currencies.
          </p>
        </>
      )}
    </>
  );
}
