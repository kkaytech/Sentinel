import {
  AlertOctagon,
  ArrowRight,
  CalendarRange,
  CheckCircle2,
  CircleDot,
  FileCheck2,
  FileUp,
  Gavel,
  Lightbulb,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  type LucideIcon,
} from "lucide-react";
import type { ReactNode } from "react";
import { Link, useNavigate } from "react-router-dom";
import { DATASET, api, type AuditEvent, type Page, type PeriodRow, type Publication, type ReviewSummary } from "../api";
import { useAuth } from "../auth";
import { Donut, Legend } from "../components/Charts";
import { DataTable, type Column } from "../components/DataTable";
import { Card, Empty, ErrorNotice, Kpi, Money, PageHeader, PageLoading, StateBadge } from "../components/ui";
import { ago, compact, plural, useLoad } from "../lib";

interface PeriodHealth {
  row: PeriodRow;
  summary: ReviewSummary | null;
}

async function loadOverview() {
  const periods = await api.get<Page<PeriodRow>>(`/datasets/${DATASET}/periods`);
  const [summaries, publications, config, first] = await Promise.all([
    Promise.all(
      periods.items.map((p) =>
        p.current_version ? api.get<ReviewSummary>(`/versions/${p.current_version.id}/review-summary`).catch(() => null) : Promise.resolve(null),
      ),
    ),
    api.get<Page<Publication>>("/publications"),
    api.get<{ rules: unknown[] }>(`/datasets/${DATASET}/config`),
    api.get<Page<AuditEvent>>("/audit/events?limit=1"),
  ]);
  // The audit list is chronological; read the last page for the most recent events.
  const offset = Math.max(0, first.total - 40);
  const recent = await api.get<Page<AuditEvent>>(`/audit/events?limit=40&offset=${offset}`);
  const meaningful = recent.items.filter((e) => !QUIET_EVENTS.has(e.event_type));
  return {
    health: periods.items.map((row, n) => ({ row, summary: summaries[n] })) as PeriodHealth[],
    publications: publications.items,
    ruleCount: config.rules.length,
    activity: [...meaningful].reverse().slice(0, 7),
  };
}

const QUIET_EVENTS = new Set(["LOGIN_SUCCEEDED", "LOGIN_FAILED", "LOGOUT", "VALIDATION_RUN_STARTED", "CONFIG_RELOAD_UNCHANGED"]);

const STAGES = ["Uploaded", "Validated", "Blockers resolved", "Approved", "Published"];

function stages(h: PeriodHealth): { done: number; blocked: boolean } {
  const s = h.summary;
  if (!h.row.current_version || !s) return { done: 0, blocked: false };
  if (h.row.derived_state === "PUBLISHED") return { done: 5, blocked: false };
  const passed = (id: string) => s.eligibility.checks.find((c) => c.id === id)?.passed ?? false;
  let done = 1;
  if (passed("E4")) done = 2;
  if (done === 2 && passed("E5")) done = 3;
  if (done === 3 && passed("E6")) done = 4;
  const blocked = done === 2 && s.blocking_non_waivable_count > 0;
  return { done, blocked };
}

function Pipeline({ health }: { health: PeriodHealth }) {
  const { done, blocked } = stages(health);
  return (
    <div className="pipeline" role="img" aria-label={`${done} of ${STAGES.length} stages complete: ${STAGES.slice(0, done).join(", ") || "none"}`}>
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
  if (!v) return { text: "Upload data", to: `/periods/${h.row.period}` };
  const review = `/versions/${v.id}/review`;
  if (h.row.derived_state === "PUBLISHED") return { text: "View publication", to: v.publication_ref ? `/publications/${v.publication_ref}` : review };
  if (!s?.current_run_id) return { text: "Run validation", to: `/versions/${v.id}` };
  if (s.blocking_non_waivable_count > 0) return { text: "Corrected upload needed", to: `/runs/${s.current_run_id}` };
  if (s.blocking_unwaived_count > 0) return { text: `Resolve ${plural(s.blocking_unwaived_count, "blocker")}`, to: `/runs/${s.current_run_id}` };
  if (s.eligibility.eligible) return { text: "Ready to publish", to: review };
  if (s.request?.status === "OPEN") return { text: "Awaiting approval", to: review };
  return { text: "Submit for review", to: review };
}

function topConfirmed(s: ReviewSummary | null) {
  const totals = (s?.live?.impact_totals ?? []).filter((t) => t.category === "CONFIRMED_DISCREPANCY");
  return totals.sort((a, b) => Number(b.amount) - Number(a.amount))[0] ?? null;
}

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

export function OverviewPage() {
  const { session, has } = useAuth();
  const navigate = useNavigate();
  const { data, error, loading } = useLoad(loadOverview, []);

  if (loading && !data) return <PageLoading />;
  if (!data) return <ErrorNotice error={error} />;

  const withVersion = data.health.filter((h) => h.row.current_version);
  const open = withVersion.filter((h) => h.row.derived_state !== "PUBLISHED");
  const blockers = open.reduce((n, h) => n + (h.summary?.blocking_unwaived_count ?? 0), 0);
  const awaiting = open.filter((h) => h.summary?.request?.status === "OPEN").length;
  const ready = open.filter((h) => h.summary?.eligibility.eligible).length;
  const published = data.health.filter((h) => h.row.derived_state === "PUBLISHED").length;

  // Issue mix across the current run of every unpublished period.
  const issues = open.flatMap((h) => h.summary?.issues ?? []);
  const mix = [
    { key: "open", label: "Blocking, open", value: issues.filter((i) => i.severity === "BLOCKING" && i.state === "OPEN").length, color: "var(--viz-confirmed)" },
    { key: "requested", label: "Waiver requested", value: issues.filter((i) => i.state === "WAIVER_REQUESTED").length, color: "var(--viz-potential)" },
    { key: "waived", label: "Waived", value: issues.filter((i) => i.state === "WAIVED").length, color: "var(--ok)" },
    { key: "warnings", label: "Warnings", value: issues.filter((i) => i.severity === "WARNING").length, color: "#c4cede" },
  ];

  const insights: { icon: LucideIcon; tone: string; text: ReactNode }[] = [];
  for (const h of open) {
    const s = h.summary;
    const v = h.row.current_version;
    if (!s || !v) continue;
    if (s.blocking_non_waivable_count > 0)
      insights.push({ icon: AlertOctagon, tone: "text-danger", text: <><strong>{h.row.period}</strong> has {plural(s.blocking_non_waivable_count, "blocking issue")} that cannot be waived. Only a corrected upload can make it publishable.</> });
    else if (s.blocking_unwaived_count > 0)
      insights.push({ icon: ShieldAlert, tone: "text-warn", text: <><strong>{h.row.period}</strong> has {plural(s.blocking_unwaived_count, "waivable blocking issue")} without a granted waiver.</> });
    if (s.request?.status === "OPEN")
      insights.push({ icon: Gavel, tone: "text-warn", text: <><strong>{h.row.period}</strong> was submitted for review {ago(s.request.submitted_at)} and is waiting for an approver.</> });
    if (s.eligibility.eligible) insights.push({ icon: CheckCircle2, tone: "text-ok", text: <><strong>{h.row.period}</strong> passes every publication check and can be published.</> });
    const confirmed = topConfirmed(s);
    if (confirmed && Number(confirmed.amount) > 0)
      insights.push({ icon: Lightbulb, tone: "text-danger", text: <><strong>{h.row.period}</strong> overstates spend by a confirmed <Money amount={confirmed.amount} currency={confirmed.currency} /> across {plural(confirmed.record_count, "record")}.</> });
  }

  const columns: Column<PeriodHealth>[] = [
    { key: "period", header: "Period", className: "strong nowrap", render: (h) => <Link to={`/periods/${h.row.period}`}>{h.row.period}</Link>, sort: (h) => h.row.period },
    { key: "state", header: "Status", className: "nowrap", render: (h) => <StateBadge state={h.row.derived_state} /> },
    { key: "pipeline", header: "Progress", render: (h) => <Pipeline health={h} /> },
    { key: "blocking", header: "Blocking", align: "right", render: (h) => (h.summary ? <span className={h.summary.blocking_unwaived_count ? "text-danger" : ""}>{h.summary.blocking_unwaived_count}</span> : "—"), sort: (h) => h.summary?.blocking_unwaived_count ?? -1 },
    { key: "confirmed", header: "Confirmed", align: "right", render: (h) => { const t = topConfirmed(h.summary); return t ? <Money amount={t.amount} currency={t.currency} compactValue={compact(t.amount)} /> : <span className="faint">None</span>; } },
    { key: "next", header: "Next step", className: "nowrap", render: (h) => { const n = nextStep(h); return <Link to={n.to} onClick={(e) => e.stopPropagation()} className="row" style={{ gap: 4, flexWrap: "nowrap" }}>{n.text}<ArrowRight width={14} height={14} aria-hidden /></Link>; } },
  ];

  return (
    <>
      <PageHeader
        title="Overview"
        subtitle={<>Welcome back, {session?.user.display_name}. Supplier invoice reporting health across every period.</>}
        actions={
          <>
            <Link className="btn" to="/publications">
              <FileCheck2 aria-hidden />
              Publications
            </Link>
            {has("ANALYST") && (
              <Link className="btn primary" to="/periods">
                <FileUp aria-hidden />
                Upload data
              </Link>
            )}
          </>
        }
      />
      <div className="kpis">
        <Kpi label="Reporting periods" value={data.health.length} hint={`${withVersion.length} with data · ${data.ruleCount} rules active`} icon={CalendarRange} tone="accent" />
        <Kpi label="Open blocking issues" value={blockers} hint={blockers ? "Must be waived or fixed at source" : "Nothing is blocking publication"} icon={ShieldAlert} tone={blockers ? "danger" : "ok"} />
        <Kpi label="Awaiting approval" value={awaiting} hint={`${ready} ready to publish`} icon={Gavel} tone={awaiting ? "warn" : undefined} />
        <Kpi label="Published" value={`${published}`} hint={data.publications[0] ? `Latest ${data.publications[0].publication_ref}` : "No publications yet"} icon={FileCheck2} tone="ok" />
      </div>

      <div className="split" style={{ marginBottom: 16 }}>
        <Card title="Reporting health" subtitle="Each period moves from upload to an immutable publication." flush>
          <DataTable
            columns={columns}
            rows={data.health}
            rowKey={(h) => h.row.period}
            onRowClick={(h) => navigate(`/periods/${h.row.period}`)}
            empty={
              <Empty title="No reporting periods yet" action={has("ANALYST") ? <Link className="btn primary" to="/periods">Upload the first period</Link> : undefined}>
                Upload a month of supplier and invoice files to begin.
              </Empty>
            }
          />
        </Card>
        <Card title="Issue status" subtitle="Current validation of unpublished periods">
          {issues.length === 0 ? (
            <Empty compact title="No open issues">Every unpublished period validated clean.</Empty>
          ) : (
            <div className="stack" style={{ alignItems: "center" }}>
              <Donut segments={mix} value={issues.length} label="issues" size={148} />
              <div style={{ width: "100%" }} className="stack-sm">
                {mix.map((m) => (
                  <div key={m.key} className="row" style={{ justifyContent: "space-between", fontSize: 13 }}>
                    <Legend items={[{ label: m.label, color: m.color }]} />
                    <strong className="num">{m.value}</strong>
                  </div>
                ))}
              </div>
            </div>
          )}
        </Card>
      </div>

      <div className="grid-2">
        <Card title="Insights" subtitle="Derived from the latest validation and review state" flush>
          {insights.length === 0 ? (
            <Empty compact title="Nothing needs attention" />
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
                      <div className="faint" style={{ fontSize: 12 }}>
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
    </>
  );
}
