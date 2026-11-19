import { CheckCircle2, Clock, FileWarning, Gavel, MessageSquare, ShieldX, XCircle } from "lucide-react";
import { useState, type FormEvent } from "react";
import { ApiError, api, type Issue, type IssueDetail, type Page, type Waiver } from "../api";
import { useAuth } from "../auth";
import { ConfirmDialog } from "../components/Dialog";
import { Badge, Card, Empty, ErrorNotice, IssueState, Notice, Skeleton } from "../components/ui";
import { toApiError, useLoad, when } from "../lib";

export const WAIVER_CATEGORIES: Record<string, string> = {
  FALSE_POSITIVE: "False positive",
  KNOWN_SOURCE_LIMITATION: "Known source limitation",
  IMMATERIAL: "Immaterial",
  OTHER: "Other",
};

function Lifecycle({ state }: { state: Issue["state"] }) {
  const order = ["OPEN", "WAIVER_REQUESTED", "WAIVED"];
  const at = order.indexOf(state);
  const steps = [
    { key: "OPEN", title: "Open", text: "Blocks publication" },
    { key: "WAIVER_REQUESTED", title: "Waiver requested", text: "Analyst justifies" },
    { key: "WAIVED", title: "Waived", text: "Approver grants" },
  ];
  return (
    <div className="lifecycle" aria-label="Issue lifecycle">
      {steps.map((s, n) => (
        <div key={s.key} className={`lifecycle-step ${at > n || state === "WAIVED" ? "done" : at === n ? "current" : ""}`}>
          <strong>{s.title}</strong>
          {s.text}
        </div>
      ))}
    </div>
  );
}

function WaiverTimeline({ waivers }: { waivers: Waiver[] }) {
  if (waivers.length === 0) return <Empty compact title="No waiver requested" />;
  return (
    <div className="timeline">
      {waivers.flatMap((w) => {
        const items = [
          <div className="tl-item" key={`${w.id}-req`}>
            <span className="tl-dot warn" aria-hidden><Gavel /></span>
            <div>
              <div className="tl-head">
                <strong>Waiver requested</strong>
                <span className="muted">by {w.requested_by?.display_name}</span>
                <span className="tl-time">{when(w.requested_at)}</span>
              </div>
              <div className="tl-body"><Badge tone="neutral">{WAIVER_CATEGORIES[w.category] ?? w.category}</Badge></div>
              <div className="tl-quote">{w.justification}</div>
            </div>
          </div>,
        ];
        if (w.decided_by) {
          const granted = w.decision === "GRANT";
          items.push(
            <div className="tl-item" key={`${w.id}-dec`}>
              <span className={`tl-dot ${granted ? "ok" : "danger"}`} aria-hidden>{granted ? <CheckCircle2 /> : <XCircle />}</span>
              <div>
                <div className="tl-head">
                  <strong>{granted ? "Granted" : "Denied"} by {w.decided_by.display_name}</strong>
                  <span className="tl-time">{when(w.decided_at)}</span>
                </div>
                {w.comment && <div className="tl-quote">{w.comment}</div>}
              </div>
            </div>,
          );
        }
        if (w.status === "STALE") {
          items.push(
            <div className="tl-item" key={`${w.id}-stale`}>
              <span className="tl-dot" aria-hidden><Clock /></span>
              <div>
                <div className="tl-head"><strong>No longer current</strong><Badge tone="neutral">{w.stale_reason?.replace(/_/g, " ").toLowerCase()}</Badge></div>
                <div className="tl-body muted">The data or its validation changed after this decision, so it no longer counts.</div>
              </div>
            </div>,
          );
        }
        return items;
      })}
    </div>
  );
}

// The issue for a finding: lifecycle, role-aware waiver actions and investigation notes.
export function IssuePanel({ runId, findingId }: { runId: string; findingId: string }) {
  const { has, session } = useAuth();
  const issues = useLoad(() => api.get<Page<Issue>>(`/runs/${runId}/issues`), [runId]);
  const issueId = issues.data?.items.find((i) => i.finding_id === findingId)?.id;
  const detail = useLoad(() => (issueId ? api.get<IssueDetail>(`/issues/${issueId}`) : Promise.resolve(null)), [issueId]);
  const [error, setError] = useState<ApiError | null>(null);
  const [category, setCategory] = useState("");
  const [justification, setJustification] = useState("");
  const [comment, setComment] = useState("");
  const [note, setNote] = useState("");
  const [confirm, setConfirm] = useState<null | "GRANT" | "DENY">(null);
  const [busy, setBusy] = useState(false);

  async function act(action: () => Promise<unknown>, after?: () => void): Promise<boolean> {
    setError(null);
    setBusy(true);
    try {
      await action();
      after?.();
      detail.reload();
      issues.reload();
      return true;
    } catch (err) {
      setError(toApiError(err));
      return false;
    } finally {
      setBusy(false);
    }
  }

  if (issues.loading && !issues.data) return <Card title="Issue"><Skeleton lines={4} /></Card>;
  if (issues.data && !issueId) {
    return (
      <Card title="Issue">
        <Empty compact icon={FileWarning} title="No issue to resolve">Informational findings do not create issues.</Empty>
      </Card>
    );
  }
  const d = detail.data;
  if (!d) return <Card title="Issue">{detail.error ? <ErrorNotice error={detail.error} /> : <Skeleton lines={4} />}</Card>;
  const issue = d.issue;
  const pending = d.waivers.find((w) => w.status === "REQUESTED");
  const ownRequest = pending?.requested_by?.id === session?.user.id;
  const canRequest = issue.state === "OPEN" && issue.severity === "BLOCKING" && issue.waivable && has("ANALYST");

  function requestWaiver(event: FormEvent) {
    event.preventDefault();
    void act(() => api.post(`/issues/${issue.id}/waivers`, { category, justification }), () => {
      setCategory("");
      setJustification("");
    });
  }

  return (
    <Card title={<span className="row" style={{ gap: 8 }}>Issue <IssueState state={issue.state} severity={issue.severity} /></span>} subtitle={`Last changed ${when(issue.state_changed_at)}`}>
      <div className="stack">
        <ErrorNotice error={error} />
        {issue.severity === "BLOCKING" && issue.waivable && issue.state !== "CLOSED_NOT_CURRENT" && <Lifecycle state={issue.state} />}
        {issue.severity === "WARNING" && <Notice tone="info">Warnings do not block publication and are not waived. The approver acknowledges every open warning when approving.</Notice>}
        {issue.severity === "BLOCKING" && !issue.waivable && (
          <Notice tone="error" title="This rule cannot be waived.">Correct the data at source and upload a new version of the period.</Notice>
        )}
        {issue.state === "CLOSED_NOT_CURRENT" && <Notice tone="info">This issue belongs to a run that is no longer current. Open the version's current run to act on it.</Notice>}

        {canRequest && (
          <form onSubmit={requestWaiver} className="stack-sm" style={{ gap: 12 }}>
            <h3>Request a waiver</h3>
            <div className="field">
              <label className="field-label" htmlFor="waiver-category">Reason</label>
              <select id="waiver-category" className="select" value={category} onChange={(e) => setCategory(e.target.value)} required>
                <option value="">Choose a reason…</option>
                {Object.entries(WAIVER_CATEGORIES).map(([value, label]) => (
                  <option key={value} value={value}>{label}</option>
                ))}
              </select>
            </div>
            <div className="field">
              <label className="field-label" htmlFor="waiver-justification">Justification</label>
              <textarea id="waiver-justification" className="textarea" value={justification} onChange={(e) => setJustification(e.target.value)} required placeholder="Explain why publishing with this issue is acceptable." />
              <span className={`field-hint ${justification.trim().length >= 30 ? "text-ok" : ""}`}>{justification.trim().length} of at least 30 characters. An approver other than you must grant it.</span>
            </div>
            <div><button className="btn primary" type="submit" disabled={busy}><Gavel aria-hidden />Request waiver</button></div>
          </form>
        )}

        {pending && has("APPROVER") && (
          <div className="stack-sm" style={{ gap: 12 }}>
            <h3>Decide the waiver request</h3>
            {ownRequest ? (
              <Notice tone="warn">You requested this waiver, so a different approver must decide it.</Notice>
            ) : (
              <>
                <div className="field">
                  <label className="field-label" htmlFor="waiver-comment">Decision comment</label>
                  <textarea id="waiver-comment" className="textarea" style={{ minHeight: 64 }} value={comment} onChange={(e) => setComment(e.target.value)} placeholder="Required when denying." />
                </div>
                <div className="row" style={{ gap: 8 }}>
                  <button className="btn primary" type="button" onClick={() => setConfirm("GRANT")} disabled={busy}><CheckCircle2 aria-hidden />Grant waiver</button>
                  <button className="btn danger" type="button" onClick={() => setConfirm("DENY")} disabled={busy}><ShieldX aria-hidden />Deny</button>
                </div>
              </>
            )}
          </div>
        )}

        <div className="divider" style={{ margin: 0 }} />
        <h3>Waiver history</h3>
        <WaiverTimeline waivers={d.waivers} />

        <div className="divider" style={{ margin: 0 }} />
        <h3>Investigation notes</h3>
        {d.notes.length === 0 ? (
          <Empty compact title="No notes yet" />
        ) : (
          <div className="timeline">
            {d.notes.map((n) => (
              <div className="tl-item" key={n.id}>
                <span className="tl-dot accent" aria-hidden><MessageSquare /></span>
                <div>
                  <div className="tl-head"><strong>{n.author?.display_name}</strong><span className="tl-time">{when(n.created_at)}</span></div>
                  <div className="tl-body">{n.body}</div>
                </div>
              </div>
            ))}
          </div>
        )}
        {(has("ANALYST") || has("APPROVER")) && (
          <form
            className="stack-sm"
            onSubmit={(e) => {
              e.preventDefault();
              void act(() => api.post(`/issues/${issue.id}/notes`, { body: note }), () => setNote(""));
            }}
          >
            <label className="sr-only" htmlFor="note">Add a note</label>
            <textarea id="note" className="textarea" style={{ minHeight: 64 }} value={note} onChange={(e) => setNote(e.target.value)} required placeholder="Add an investigation note. Notes cannot be edited or deleted." />
            <div><button type="submit" className="btn" disabled={busy || !note.trim()}><MessageSquare aria-hidden />Add note</button></div>
          </form>
        )}
      </div>
      <ConfirmDialog
        open={confirm !== null && !!pending}
        title={confirm === "GRANT" ? "Grant this waiver?" : "Deny this waiver?"}
        confirmLabel={confirm === "GRANT" ? "Grant waiver" : "Deny waiver"}
        danger={confirm === "DENY"}
        busy={busy}
        onClose={() => setConfirm(null)}
        onConfirm={() =>
          pending &&
          void act(() => api.post(`/waivers/${pending.id}/decision`, { decision: confirm, comment }), () => setComment("")).then(() => setConfirm(null))
        }
      >
        {confirm === "GRANT" ? (
          <p>
            The blocking issue <strong>{issue.rule_id}</strong> will no longer block publication of this exact version and validation run. Your decision is recorded in the audit trail and the publication manifest.
          </p>
        ) : (
          <p>The issue returns to Open and keeps blocking publication. {comment.trim() ? "Your comment is sent with the decision." : "A comment is required to deny a waiver."}</p>
        )}
      </ConfirmDialog>
    </Card>
  );
}
