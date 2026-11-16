import { useState, type FormEvent } from "react";
import { ApiError, api, type Issue, type IssueDetail, type Page } from "../api";
import { useAuth } from "../auth";
import { Card, Empty, ErrorBox, Loading, toApiError, useLoad, when } from "../ui";

const CATEGORIES: Record<string, string> = {
  FALSE_POSITIVE: "False positive",
  KNOWN_SOURCE_LIMITATION: "Known source limitation",
  IMMATERIAL: "Immaterial",
  OTHER: "Other",
};

export const ISSUE_STATES: Record<string, string> = {
  OPEN: "Open",
  WAIVER_REQUESTED: "Waiver requested",
  WAIVED: "Waived",
  CLOSED_NOT_CURRENT: "Closed (run no longer current)",
};

export function IssueState({ state }: { state: string }) {
  const tone = state === "WAIVED" ? "ok" : state === "OPEN" ? "sev-blocking" : state === "WAIVER_REQUESTED" ? "sev-warning" : "state-superseded";
  return <span className={`badge ${tone}`}>{ISSUE_STATES[state] ?? state}</span>;
}

// The issue for a finding: its workflow state, waivers and investigation notes (FS S6).
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

  async function act(action: () => Promise<unknown>, after?: () => void) {
    setError(null);
    try {
      await action();
      after?.();
      detail.reload();
    } catch (err) {
      setError(toApiError(err));
    }
  }

  if (issues.loading && !issues.data) return <Loading what="Loading issue" />;
  if (issues.data && !issueId) {
    return (
      <Card title="Issue">
        <Empty>Informational findings create no issue: nothing needs to be resolved.</Empty>
      </Card>
    );
  }
  const d = detail.data;
  if (!d) return <ErrorBox error={detail.error ?? issues.error} />;
  const issue = d.issue;
  const pending = d.waivers.find((w) => w.status === "REQUESTED");
  const ownRequest = pending?.requested_by?.id === session?.user.id;

  function requestWaiver(event: FormEvent) {
    event.preventDefault();
    void act(
      () => api.post(`/issues/${issue.id}/waivers`, { category, justification }),
      () => {
        setCategory("");
        setJustification("");
      },
    );
  }

  return (
    <Card
      title={
        <>
          Issue <IssueState state={issue.state} />
        </>
      }
    >
      <ErrorBox error={error} />
      {issue.severity === "WARNING" && <p className="muted">Warnings do not block publication and are not waived. The approver acknowledges them at approval.</p>}
      {issue.severity === "BLOCKING" && !issue.waivable && (
        <div className="alert warn">This rule cannot be waived. Correct the data at source and upload a new version.</div>
      )}
      {issue.state === "CLOSED_NOT_CURRENT" && <div className="alert info">This issue belongs to a run that is no longer current. Open the version's current run to act on it.</div>}

      {issue.state === "OPEN" && issue.severity === "BLOCKING" && issue.waivable && has("ANALYST") && (
        <form onSubmit={requestWaiver}>
          <h3>Request a waiver</h3>
          <div className="row">
            <div className="field">
              <label htmlFor="waiver-category">Reason</label>
              <select id="waiver-category" value={category} onChange={(e) => setCategory(e.target.value)} required>
                <option value="">Choose…</option>
                {Object.entries(CATEGORIES).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <div className="field">
            <label htmlFor="waiver-justification">Justification (at least 30 characters) — {justification.trim().length} entered</label>
            <textarea id="waiver-justification" value={justification} onChange={(e) => setJustification(e.target.value)} required />
          </div>
          <button className="primary" type="submit">
            Request waiver
          </button>
        </form>
      )}

      {pending && has("APPROVER") && (
        <div>
          <h3>Decide the waiver request</h3>
          {ownRequest ? (
            <div className="alert warn">You requested this waiver, so a different approver must decide it.</div>
          ) : (
            <>
              <div className="field">
                <label htmlFor="waiver-comment">Comment (required to deny)</label>
                <textarea id="waiver-comment" value={comment} onChange={(e) => setComment(e.target.value)} />
              </div>
              <div className="actions">
                <button className="primary" onClick={() => void act(() => api.post(`/waivers/${pending.id}/decision`, { decision: "GRANT", comment }), () => setComment(""))}>
                  Grant waiver
                </button>
                <button className="danger" onClick={() => void act(() => api.post(`/waivers/${pending.id}/decision`, { decision: "DENY", comment }), () => setComment(""))}>
                  Deny
                </button>
              </div>
            </>
          )}
        </div>
      )}

      <h3>Waiver history</h3>
      {d.waivers.length === 0 ? (
        <Empty>No waiver has been requested.</Empty>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Status</th>
              <th>Reason</th>
              <th>Justification</th>
              <th>Requested</th>
              <th>Decision</th>
            </tr>
          </thead>
          <tbody>
            {d.waivers.map((w) => (
              <tr key={w.id}>
                <td>
                  <span className={`badge ${w.status === "GRANTED" ? "ok" : w.status === "DENIED" ? "sev-blocking" : w.status === "STALE" ? "state-superseded" : "sev-warning"}`}>{w.status}</span>
                  {w.stale_reason && <div className="muted">{w.stale_reason}</div>}
                </td>
                <td>{CATEGORIES[w.category] ?? w.category}</td>
                <td>{w.justification}</td>
                <td>
                  {w.requested_by?.display_name}
                  <div className="muted">{when(w.requested_at)}</div>
                </td>
                <td>
                  {w.decided_by ? (
                    <>
                      {w.decision} by {w.decided_by.display_name}
                      <div className="muted">{when(w.decided_at)}</div>
                      {w.comment && <div>“{w.comment}”</div>}
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

      <h3>Investigation notes</h3>
      {d.notes.length === 0 && <Empty>No notes yet.</Empty>}
      <ul className="plain">
        {d.notes.map((n) => (
          <li key={n.id}>
            <strong>{n.author?.display_name}</strong> <span className="muted">{when(n.created_at)}</span>
            <div>{n.body}</div>
          </li>
        ))}
      </ul>
      {(has("ANALYST") || has("APPROVER")) && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void act(() => api.post(`/issues/${issue.id}/notes`, { body: note }), () => setNote(""));
          }}
        >
          <div className="field">
            <label htmlFor="note">Add a note (notes cannot be edited or deleted)</label>
            <textarea id="note" value={note} onChange={(e) => setNote(e.target.value)} required />
          </div>
          <button type="submit">Add note</button>
        </form>
      )}
    </Card>
  );
}
