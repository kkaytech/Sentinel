import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ApiError, api, type EligibilityCheck, type ReviewSummary } from "../api";
import { useAuth } from "../auth";
import { CATEGORY_LABELS, Card, Empty, ErrorBox, Loading, Money, Severity, StateBadge, toApiError, useLoad, when } from "../ui";
import { IssueState } from "./IssuePanel";

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

function CheckRow({ check }: { check: EligibilityCheck }) {
  const detail = check.details as { rule_ids?: string[]; unresolved?: { rule_id: string; reason: string }[]; publication_ref?: string };
  return (
    <tr>
      <td className="mono">{check.id}</td>
      <td>{CHECKS[check.id] ?? check.id}</td>
      <td>
        <span className={`badge ${check.passed ? "ok" : "sev-blocking"}`}>{check.passed ? "Pass" : "Fail"}</span>
      </td>
      <td>
        {check.code && (
          <>
            <span className="mono">{check.code}</span> — {CODES[check.code] ?? ""}
            {detail.rule_ids && <div className="muted">Cannot be waived: {detail.rule_ids.join(", ")}</div>}
            {detail.unresolved && detail.unresolved.length > 0 && (
              <div className="muted">Unresolved: {detail.unresolved.map((u) => `${u.rule_id} (${u.reason === "STALE_WAIVER" ? "waiver is stale" : "no waiver"})`).join(", ")}</div>
            )}
            {detail.publication_ref && <div className="muted">{detail.publication_ref}</div>}
          </>
        )}
      </td>
    </tr>
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

  async function act(action: () => Promise<unknown>) {
    setError(null);
    setBusy(true);
    try {
      await action();
    } catch (err) {
      setError(toApiError(err));
    } finally {
      setBusy(false);
      summary.reload();
    }
  }

  const s = summary.data;
  if (!s) return summary.error ? <ErrorBox error={summary.error} /> : <Loading />;
  const v = s.version;
  const request = s.request;
  const open = request?.status === "OPEN" ? request : null;
  const ownSubmission = open?.submitted_by?.id === session?.user.id;
  const published = v.publication_ref !== null;
  const refused = (error?.details.checks as EligibilityCheck[] | undefined) ?? null;

  return (
    <>
      <div className="crumbs">
        <Link to="/periods">Periods</Link> / <Link to={`/periods/${v.period}`}>{v.period}</Link> / <Link to={`/versions/${v.id}`}>{v.label}</Link> / review
      </div>
      <div className="page-head">
        <div>
          <h1>
            Review and publish {v.label} <StateBadge state={v.derived_state} />
          </h1>
          <p className="muted mono">content hash {v.content_hash}</p>
        </div>
      </div>
      <ErrorBox error={error} />
      {published && (
        <div className="alert ok">
          Published as <Link to={`/publications/${v.publication_ref}`}>{v.publication_ref}</Link>. The snapshot is immutable.
        </div>
      )}
      {!s.current_run_id && <div className="alert warn">This version has no current validation run. Run validation before review.</div>}
      {s.blocking_unwaived_count > 0 && (
        <div className="alert error">
          {s.blocking_unwaived_count} blocking issue(s) are not waived — publication will be refused.
          {s.blocking_non_waivable_count > 0 && ` ${s.blocking_non_waivable_count} of them cannot be waived and need a corrected upload.`}
        </div>
      )}
      {s.differences.length > 0 && open && (
        <div className="alert warn">Since this review was submitted, the following changed: {s.differences.map((d) => d.replace(/_/g, " ")).join(", ")}. The live state is shown below.</div>
      )}

      <Card title={`Publication checklist — ${published ? "published" : s.eligibility.eligible ? "eligible" : "not eligible"}`}>
        <p className="muted" style={{ marginTop: 0 }}>
          {published
            ? "This version passed every check when it was published. The last check now fails only because the period is taken: each period can be published once."
            : "Computed by the server with the same check that publish uses. Nothing here is decided in the browser."}
        </p>
        <table>
          <thead>
            <tr>
              <th>Check</th>
              <th>Requirement</th>
              <th>Result</th>
              <th>Why</th>
            </tr>
          </thead>
          <tbody>
            {(refused ?? s.eligibility.checks).map((c) => (
              <CheckRow key={c.id} check={c} />
            ))}
          </tbody>
        </table>
        {!published && (has("ANALYST") || has("APPROVER")) && (
          <div className="actions" style={{ marginTop: 12 }}>
            <button className="primary" disabled={busy || !s.eligibility.eligible} onClick={() => void act(() => api.post(`/versions/${v.id}/publish`))}>
              Publish this version
            </button>
            {!s.eligibility.eligible && <span className="muted">Every check must pass before publishing.</span>}
          </div>
        )}
      </Card>

      {s.current_run_id && !published && (
        <Card title="Review request">
          {!open && has("ANALYST") && (
            <form
              onSubmit={(e) => {
                e.preventDefault();
                void act(async () => {
                  await api.post(`/versions/${v.id}/review-requests`, { note });
                  setNote("");
                });
              }}
            >
              <p className="muted" style={{ marginTop: 0 }}>
                {request ? `The last request is ${request.status}${request.stale_reason ? ` (${request.stale_reason})` : ""}. You can submit again.` : "Submit this version to an approver. The current findings, impact and waivers are frozen as a snapshot."}
              </p>
              <div className="field">
                <label htmlFor="review-note">Note for the approver</label>
                <textarea id="review-note" value={note} onChange={(e) => setNote(e.target.value)} required />
              </div>
              <button className="primary" type="submit" disabled={busy}>
                Submit for review
              </button>
            </form>
          )}
          {!open && !has("ANALYST") && <Empty>No review request is open. An analyst submits the version for review.</Empty>}
          {open && (
            <>
              <dl className="facts">
                <dt>Submitted</dt>
                <dd>
                  {open.submitted_by?.display_name}, {when(open.submitted_at)}
                </dd>
                <dt>Note</dt>
                <dd>{open.note}</dd>
              </dl>
              {has("APPROVER") &&
                (ownSubmission ? (
                  <div className="alert warn" style={{ marginTop: 12 }}>You submitted this review, so a different approver must decide it.</div>
                ) : (
                  <div style={{ marginTop: 12 }}>
                    <label style={{ color: "inherit" }}>
                      <input type="checkbox" checked={acknowledged} onChange={(e) => setAcknowledged(e.target.checked)} /> I acknowledge the {s.open_warning_count} open warning(s) on this version.
                    </label>
                    <div className="field" style={{ marginTop: 10 }}>
                      <label htmlFor="decision-comment">Comment (required to reject)</label>
                      <textarea id="decision-comment" value={comment} onChange={(e) => setComment(e.target.value)} />
                    </div>
                    <div className="actions">
                      <button
                        className="primary"
                        disabled={busy || !acknowledged}
                        onClick={() => void act(() => api.post(`/review-requests/${open.id}/decision`, { decision: "APPROVE", comment, acknowledged_warning_count: s.open_warning_count }))}
                      >
                        Approve
                      </button>
                      <button className="danger" disabled={busy} onClick={() => void act(() => api.post(`/review-requests/${open.id}/decision`, { decision: "REJECT", comment }))}>
                        Reject
                      </button>
                    </div>
                  </div>
                ))}
              {!has("APPROVER") && <p className="muted">Waiting for an approver's decision.</p>}
            </>
          )}
        </Card>
      )}

      <Card title={`Issues on the current run (${s.issues.length})`}>
        {s.issues.length === 0 ? (
          <Empty>No blocking issues or warnings.</Empty>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Severity</th>
                <th>Rule</th>
                <th>Finding</th>
                <th>State</th>
              </tr>
            </thead>
            <tbody>
              {s.issues.map((i) => (
                <tr key={i.id}>
                  <td>
                    <Severity value={i.severity} />
                  </td>
                  <td className="mono">
                    <Link to={`/findings/${i.finding_id}`}>{i.rule_id}</Link>
                  </td>
                  <td>{i.message}</td>
                  <td>{i.severity === "WARNING" ? "Acknowledged at approval" : <IssueState state={i.state} />}{i.severity === "BLOCKING" && !i.waivable ? " · cannot be waived" : ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>

      {s.live && (
        <Card title="Financial impact (live)">
          {s.live.impact_totals.length === 0 ? (
            <Empty>No financial impact was found.</Empty>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>Category</th>
                  <th className="num">Amount</th>
                  <th className="num">Records</th>
                </tr>
              </thead>
              <tbody>
                {s.live.impact_totals.map((t) => (
                  <tr key={t.category + t.currency}>
                    <td>{CATEGORY_LABELS[t.category] ?? t.category}</td>
                    <td className="num">
                      <Money amount={t.amount} currency={t.currency} />
                    </td>
                    <td className="num">{t.record_count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {s.current_run_id && (
            <p>
              <Link to={`/runs/${s.current_run_id}/impact`}>Full reporting impact</Link>
            </p>
          )}
        </Card>
      )}

      <Card title="Review history">
        {s.history.length === 0 ? (
          <Empty>No review has been submitted for this version.</Empty>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Status</th>
                <th>Submitted</th>
                <th>Note</th>
                <th>Decision</th>
              </tr>
            </thead>
            <tbody>
              {s.history.map((r) => (
                <tr key={r.id}>
                  <td>
                    <span className={`badge ${r.status === "APPROVED" ? "ok" : r.status === "REJECTED" ? "sev-blocking" : r.status === "STALE" ? "state-superseded" : "sev-warning"}`}>{r.status}</span>
                    {r.stale_reason && <div className="muted">{r.stale_reason}</div>}
                  </td>
                  <td>
                    {r.submitted_by?.display_name}
                    <div className="muted">{when(r.submitted_at)}</div>
                  </td>
                  <td>{r.note}</td>
                  <td>
                    {r.decided_by ? (
                      <>
                        {r.decision} by {r.decided_by.display_name}
                        <div className="muted">{when(r.decided_at)}</div>
                        {r.acknowledged_warning_count !== null && <div className="muted">{r.acknowledged_warning_count} warning(s) acknowledged</div>}
                        {r.comment && <div>“{r.comment}”</div>}
                      </>
                    ) : (
                      "—"
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </>
  );
}
