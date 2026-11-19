import { BarChart3, CheckCircle2, Clock, FileCheck2, Gavel, ListChecks, Send, ShieldCheck, ThumbsDown, ThumbsUp, XCircle } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ApiError, api, type EligibilityCheck, type ReviewRequest, type ReviewSummary } from "../api";
import { useAuth } from "../auth";
import { ConfirmDialog } from "../components/Dialog";
import { DataTable } from "../components/DataTable";
import { Badge, Card, Empty, ErrorNotice, IssueState, Money, Notice, PageHeader, PageLoading, Severity, StateBadge, Tabs } from "../components/ui";
import { CATEGORY_LABELS, ago, toApiError, useLoad, when } from "../lib";

const CHECKS: Record<string, string> = {
  E1: "You are allowed to publish",
  E2: "This is the period's current version",
  E3: "Stored content matches its recorded hash",
  E4: "Validation is current",
  E5: "Every blocking issue is resolved",
  E6: "Approved by a different user",
  E7: "The period has not been published yet",
};

const CODES: Record<string, string> = {
  PERMISSION_DENIED: "Your role cannot publish.",
  VERSION_SUPERSEDED: "A later version has replaced this one.",
  INTEGRITY_FAILURE: "The stored data no longer matches its content hash.",
  NO_CURRENT_VALIDATION: "Run validation first.",
  STALE_VALIDATION: "The rule set changed after the last run. Run validation again.",
  NON_WAIVABLE_BLOCKING_ISSUES: "Blocking issues that cannot be waived remain. Fix the data and upload again.",
  UNRESOLVED_BLOCKING_ISSUES: "Blocking issues have no granted, current waiver.",
  MISSING_APPROVAL: "No approval has been recorded.",
  STALE_APPROVAL: "The approval was given for earlier data or an earlier validation.",
  SEGREGATION_OF_DUTIES: "The approver is the person who submitted the review.",
  PERIOD_ALREADY_PUBLISHED: "This period already has a publication.",
};

function Checklist({ checks }: { checks: EligibilityCheck[] }) {
  return (
    <div className="checklist">
      {checks.map((check) => {
        const detail = check.details as { rule_ids?: string[]; unresolved?: { rule_id: string; reason: string }[]; publication_ref?: string };
        return (
          <div className="check-item" key={check.id}>
            <span className={`check-icon ${check.passed ? "pass" : "fail"}`} aria-hidden>{check.passed ? <CheckCircle2 /> : <XCircle />}</span>
            <div>
              <div className="check-title">
                {CHECKS[check.id] ?? check.id}
                <span className="faint mono" style={{ fontWeight: 400 }}>{check.id}</span>
                <span className="sr-only">{check.passed ? "passed" : "failed"}</span>
              </div>
              {check.code && (
                <div className="check-why">
                  <code className="text-danger">{check.code}</code> · {CODES[check.code] ?? ""}
                  {detail.rule_ids && <div>Cannot be waived: {detail.rule_ids.map((r) => <code key={r} style={{ marginRight: 6 }}>{r}</code>)}</div>}
                  {detail.unresolved && detail.unresolved.length > 0 && (
                    <div>Unresolved: {detail.unresolved.map((u) => `${u.rule_id} (${u.reason === "STALE_WAIVER" ? "waiver is stale" : "no waiver"})`).join(", ")}</div>
                  )}
                  {detail.publication_ref && <div><Link to={`/publications/${detail.publication_ref}`}>{detail.publication_ref}</Link></div>}
                </div>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function RequestStatus({ request }: { request: ReviewRequest }) {
  const tone = request.status === "APPROVED" ? "ok" : request.status === "REJECTED" ? "danger" : request.status === "OPEN" ? "warn" : "neutral";
  const label = request.status === "OPEN" ? "Awaiting decision" : request.status.charAt(0) + request.status.slice(1).toLowerCase();
  return <Badge tone={tone} dot>{label}</Badge>;
}

function History({ history }: { history: ReviewRequest[] }) {
  if (history.length === 0) return <Empty compact title="No review submitted yet" />;
  return (
    <div className="timeline">
      {history.flatMap((r) => {
        const items = [];
        if (r.decided_by) {
          const approved = r.decision === "APPROVE";
          items.push(
            <div className="tl-item" key={`${r.id}-d`}>
              <span className={`tl-dot ${approved ? "ok" : "danger"}`} aria-hidden>{approved ? <ThumbsUp /> : <ThumbsDown />}</span>
              <div>
                <div className="tl-head"><strong>{approved ? "Approved" : "Rejected"} by {r.decided_by.display_name}</strong><span className="tl-time">{when(r.decided_at)}</span></div>
                {r.acknowledged_warning_count !== null && <div className="tl-body muted">{r.acknowledged_warning_count} warning(s) acknowledged</div>}
                {r.comment && <div className="tl-quote">{r.comment}</div>}
              </div>
            </div>,
          );
        }
        if (r.status === "STALE") {
          items.push(
            <div className="tl-item" key={`${r.id}-s`}>
              <span className="tl-dot" aria-hidden><Clock /></span>
              <div>
                <div className="tl-head"><strong>No longer current</strong><Badge tone="neutral">{r.stale_reason?.replace(/_/g, " ").toLowerCase()}</Badge></div>
                <div className="tl-body muted">The data or its validation changed after this review.</div>
              </div>
            </div>,
          );
        }
        items.push(
          <div className="tl-item" key={`${r.id}-s0`}>
            <span className="tl-dot accent" aria-hidden><Send /></span>
            <div>
              <div className="tl-head"><strong>Submitted by {r.submitted_by?.display_name}</strong><span className="tl-time">{when(r.submitted_at)}</span></div>
              <div className="tl-quote">{r.note}</div>
            </div>
          </div>,
        );
        return items;
      })}
    </div>
  );
}

export function ReviewPage() {
  const { versionId = "" } = useParams();
  const { has, session } = useAuth();
  const summary = useLoad(() => api.get<ReviewSummary>(`/versions/${versionId}/review-summary`), [versionId]);
  const [error, setError] = useState<ApiError | null>(null);
  const [note, setNote] = useState("");
  const [comment, setComment] = useState("");
  const [acknowledged, setAcknowledged] = useState(false);
  const [busy, setBusy] = useState(false);
  const [confirm, setConfirm] = useState<null | "APPROVE" | "REJECT" | "PUBLISH">(null);

  async function act(action: () => Promise<unknown>) {
    setError(null);
    setBusy(true);
    try {
      await action();
    } catch (err) {
      setError(toApiError(err));
    } finally {
      setBusy(false);
      setConfirm(null);
      summary.reload();
    }
  }

  const s = summary.data;
  if (summary.loading && !s) return <PageLoading />;
  if (!s) return <ErrorNotice error={summary.error} />;
  const v = s.version;
  const request = s.request;
  const open = request?.status === "OPEN" ? request : null;
  const ownSubmission = open?.submitted_by?.id === session?.user.id;
  const published = v.publication_ref !== null && v.publication_ref !== undefined;
  const refused = (error?.details.checks as EligibilityCheck[] | undefined) ?? null;
  const checks = refused ?? s.eligibility.checks;
  const passedCount = checks.filter((c) => c.passed).length;
  const canPublish = !published && (has("ANALYST") || has("APPROVER"));
  const blocking = s.issues.filter((i) => i.severity === "BLOCKING");
  const warnings = s.issues.filter((i) => i.severity === "WARNING");

  return (
    <>
      <PageHeader
        crumbs={[{ label: "Reporting periods", to: "/periods" }, { label: v.period, to: `/periods/${v.period}` }, { label: v.label, to: `/versions/${v.id}` }, { label: "Review and publish" }]}
        title="Review and publish"
        badge={<StateBadge state={v.derived_state} />}
        subtitle={<><span className="mono">{v.label}</span> · content hash <code>{v.content_hash.slice(0, 16)}…</code></>}
        actions={
          canPublish ? (
            <button className="btn primary" disabled={busy || !s.eligibility.eligible} onClick={() => setConfirm("PUBLISH")}>
              <FileCheck2 aria-hidden />
              Publish this version
            </button>
          ) : undefined
        }
      />
      {s.current_run_id && (
        <Tabs
          items={[
            { to: `/runs/${s.current_run_id}`, label: "Findings", icon: ListChecks, end: true },
            { to: `/runs/${s.current_run_id}/impact`, label: "Reporting impact", icon: BarChart3 },
            { to: `/versions/${v.id}/review`, label: "Review and publish", icon: Gavel },
          ]}
        />
      )}
      <div className="stack">
        <ErrorNotice error={error} />
        {published && (
          <Notice tone="ok" title="Published">
            This version is published as <Link to={`/publications/${v.publication_ref}`}>{v.publication_ref}</Link>. The snapshot is immutable.
          </Notice>
        )}
        {!s.current_run_id && <Notice tone="warn" title="No current validation">Run validation under the active rule set before review.</Notice>}
        {!published && s.blocking_unwaived_count > 0 && (
          <Notice tone="error" title={`${s.blocking_unwaived_count} blocking issue(s) are not waived — publication will be refused.`}>
            {s.blocking_non_waivable_count > 0 ? `${s.blocking_non_waivable_count} of them cannot be waived and need a corrected upload.` : "Each one needs a waiver granted by an approver."}
          </Notice>
        )}
        {s.differences.length > 0 && open && (
          <Notice tone="warn" title="Changed since submission">{s.differences.map((d) => d.replace(/_/g, " ")).join(", ")} changed after this review was submitted. The live state is shown.</Notice>
        )}

        <div className="split">
          <div className="stack">
            <Card
              title={`Publication checklist — ${published ? "published" : s.eligibility.eligible ? "eligible" : "not eligible"}`}
              subtitle={published ? "This version passed every check when it was published. The last check now fails only because each period can be published once." : "Computed by the server with the same check that publish uses."}
              actions={<Badge tone={published || s.eligibility.eligible ? "ok" : "danger"}>{passedCount} of {checks.length} passed</Badge>}
            >
              <Checklist checks={checks} />
            </Card>
            <Card title="Issues on the current run" subtitle={`${blocking.length} blocking · ${warnings.length} warnings`} flush>
              <DataTable
                rows={s.issues}
                rowKey={(i) => i.id}
                empty={<Empty compact icon={ShieldCheck} title="No blocking issues or warnings" />}
                columns={[
                  { key: "sev", header: "Severity", className: "nowrap", render: (i) => <Severity value={i.severity} /> },
                  { key: "rule", header: "Rule", className: "nowrap", render: (i) => <Link to={`/findings/${i.finding_id}`} className="rule-id">{i.rule_id}</Link> },
                  { key: "msg", header: "Finding", className: "wrap", render: (i) => i.message },
                  { key: "state", header: "Status", className: "nowrap", render: (i) => (<span className="row" style={{ gap: 6, flexWrap: "nowrap" }}><IssueState state={i.state} severity={i.severity} />{i.severity === "BLOCKING" && !i.waivable && <Badge tone="danger">not waivable</Badge>}</span>) },
                ]}
              />
            </Card>
          </div>

          <div className="stack">
            {s.current_run_id && !published && (
              <Card title="Review request" actions={request ? <RequestStatus request={request} /> : undefined}>
                {!open && has("ANALYST") && (
                  <form
                    className="stack-sm"
                    style={{ gap: 12 }}
                    onSubmit={(e) => {
                      e.preventDefault();
                      void act(async () => {
                        await api.post(`/versions/${v.id}/review-requests`, { note });
                        setNote("");
                      });
                    }}
                  >
                    <p className="muted">
                      {request ? `The last request was ${request.status.toLowerCase()}${request.stale_reason ? ` (${request.stale_reason.replace(/_/g, " ").toLowerCase()})` : ""}. You can submit again.` : "The current findings, impact and waivers are frozen as a snapshot for the approver."}
                    </p>
                    <div className="field">
                      <label className="field-label" htmlFor="review-note">Note for the approver</label>
                      <textarea id="review-note" className="textarea" value={note} onChange={(e) => setNote(e.target.value)} required placeholder="Summarise what changed and why it can be published." />
                    </div>
                    <div><button className="btn primary" type="submit" disabled={busy}><Send aria-hidden />Submit for review</button></div>
                  </form>
                )}
                {!open && !has("ANALYST") && <Empty compact title="No review request is open.">An analyst submits the version for review.</Empty>}
                {open && (
                  <div className="stack">
                    <div className="tl-quote" style={{ marginTop: 0 }}>
                      <div className="faint" style={{ fontSize: 13, marginBottom: 2 }}>{open.submitted_by?.display_name} · {ago(open.submitted_at)}</div>
                      {open.note}
                    </div>
                    {has("APPROVER") &&
                      (ownSubmission ? (
                        <Notice tone="warn">You submitted this review, so a different approver must decide it.</Notice>
                      ) : (
                        <>
                          <label className="checkbox">
                            <input type="checkbox" checked={acknowledged} onChange={(e) => setAcknowledged(e.target.checked)} />
                            <span>I acknowledge the {s.open_warning_count} open warning(s) on this version.</span>
                          </label>
                          <div className="field">
                            <label className="field-label" htmlFor="decision-comment">Comment</label>
                            <textarea id="decision-comment" className="textarea" style={{ minHeight: 64 }} value={comment} onChange={(e) => setComment(e.target.value)} placeholder="Required when rejecting." />
                          </div>
                          <div className="row" style={{ gap: 8 }}>
                            <button className="btn primary" disabled={busy || !acknowledged} onClick={() => setConfirm("APPROVE")}><ThumbsUp aria-hidden />Approve</button>
                            <button className="btn danger" disabled={busy} onClick={() => setConfirm("REJECT")}><ThumbsDown aria-hidden />Reject</button>
                          </div>
                        </>
                      ))}
                    {!has("APPROVER") && <p className="muted">Waiting for an approver's decision.</p>}
                  </div>
                )}
              </Card>
            )}
            {s.live && (
              <Card title="Financial impact" subtitle="Live totals for the current run" flush actions={s.current_run_id ? <Link className="btn sm ghost" to={`/runs/${s.current_run_id}/impact`}>Details</Link> : undefined}>
                {s.live.impact_totals.length === 0 ? (
                  <Empty compact title="No financial impact" />
                ) : (
                  <DataTable
                    rows={s.live.impact_totals}
                    rowKey={(t) => t.category + t.currency}
                    columns={[
                      { key: "cat", header: "Category", className: "nowrap", render: (t) => <Badge tone={t.category === "CONFIRMED_DISCREPANCY" ? "danger" : "warn"}>{CATEGORY_LABELS[t.category]}</Badge> },
                      { key: "amt", header: "Amount", align: "right", render: (t) => <Money amount={t.amount} currency={t.currency} /> },
                    ]}
                  />
                )}
              </Card>
            )}
            <Card title="Review history">
              <History history={s.history} />
            </Card>
          </div>
        </div>
      </div>

      <ConfirmDialog
        open={confirm === "APPROVE" && !!open}
        title="Approve this version?"
        confirmLabel="Approve version"
        busy={busy}
        icon={ThumbsUp}
        onClose={() => setConfirm(null)}
        onConfirm={() => open && void act(() => api.post(`/review-requests/${open.id}/decision`, { decision: "APPROVE", comment, acknowledged_warning_count: s.open_warning_count }))}
      >
        <p>You approve <strong className="mono">{v.label}</strong> with its current validation run, acknowledging {s.open_warning_count} warning(s). The approval binds to this exact data: any new upload or run makes it stale.</p>
      </ConfirmDialog>
      <ConfirmDialog
        open={confirm === "REJECT" && !!open}
        title="Reject this review?"
        confirmLabel="Reject review"
        danger
        busy={busy}
        onClose={() => setConfirm(null)}
        onConfirm={() => open && void act(() => api.post(`/review-requests/${open.id}/decision`, { decision: "REJECT", comment }))}
      >
        <p>The analyst can resubmit after addressing your comment. {comment.trim() ? "" : "A comment is required to reject."}</p>
      </ConfirmDialog>
      <ConfirmDialog
        open={confirm === "PUBLISH"}
        title="Publish this version?"
        confirmLabel="Publish"
        busy={busy}
        icon={FileCheck2}
        onClose={() => setConfirm(null)}
        onConfirm={() => void act(() => api.post(`/versions/${v.id}/publish`))}
      >
        <p>
          Sentinel re-checks eligibility, then writes an immutable snapshot of <strong className="mono">{v.label}</strong> with a hash-sealed manifest. A period can be published only once, and this cannot be undone.
        </p>
      </ConfirmDialog>
    </>
  );
}
