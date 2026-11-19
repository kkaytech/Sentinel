import { ChevronDown, ChevronRight, ScrollText } from "lucide-react";
import { Fragment, useState } from "react";
import { api, type AuditEvent, type Page } from "../api";
import { Pager } from "../components/DataTable";
import { Card, Empty, ErrorNotice, PageHeader, Skeleton } from "../components/ui";
import { plural, useLoad, useUrlState, when } from "../lib";
import { describeEvent } from "./Overview";

const PAGE_SIZE = 50;
const EVENT_TYPES = [
  "VERSION_CREATED", "VERSION_SUPERSEDED", "INGESTION_FAILED", "INGESTION_DUPLICATE", "INGESTION_REJECTED",
  "VALIDATION_RUN_STARTED", "VALIDATION_RUN_COMPLETED", "VALIDATION_RUN_FAILED", "ISSUES_OPENED",
  "ISSUES_CLOSED_NOT_CURRENT", "ISSUE_NOTE_ADDED", "WAIVER_REQUESTED", "WAIVER_GRANTED", "WAIVER_DENIED",
  "WAIVER_STALE", "REVIEW_SUBMITTED", "REVIEW_APPROVED", "REVIEW_REJECTED", "REVIEW_REQUEST_STALE",
  "DATASET_PUBLISHED", "PUBLICATION_REFUSED", "PUBLICATION_VERIFIED", "CONFIG_ACTIVATED", "LOGIN_SUCCEEDED",
  "LOGIN_FAILED", "LOGOUT", "USER_CREATED", "USER_UPDATED",
];
const ENTITY_TYPES = ["dataset_version", "dataset_period", "ingestion_attempt", "validation_run", "issue", "waiver", "review_request", "publication", "config", "user"];

export function AuditPage() {
  // Filters and the page live in the address, so returning to the audit trail restores them.
  const [view, setView] = useUrlState({ event: "", entity: "", offset: "0" });
  const eventType = view.event;
  const entityType = view.entity;
  const offset = Math.max(0, Number(view.offset) || 0);
  const setOffset = (n: number) => setView({ offset: String(n) });
  const [expanded, setExpanded] = useState<number | null>(null);
  const query = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String(offset) });
  if (eventType) query.set("event_type", eventType);
  if (entityType) query.set("entity_type", entityType);
  const events = useLoad(() => api.get<Page<AuditEvent>>(`/audit/events?${query}`), [query.toString()]);

  return (
    <>
      <PageHeader title="Audit trail" subtitle="Append-only. Every state change is recorded in the same transaction as the change itself." />
      <Card flush>
        <div className="table-tools">
          <div className="field" style={{ width: 240 }}>
            <label className="field-label" htmlFor="event-type">Event type</label>
            <select id="event-type" className="select" value={eventType} onChange={(e) => setView({ event: e.target.value, offset: "0" })}>
              <option value="">All events</option>
              {EVENT_TYPES.map((t) => (
                <option key={t} value={t}>{describeEvent({ event_type: t, payload: {}, entity_type: "", entity_id: "" } as unknown as AuditEvent).text}</option>
              ))}
            </select>
          </div>
          <div className="field" style={{ width: 220 }}>
            <label className="field-label" htmlFor="entity-type">Entity type</label>
            <select id="entity-type" className="select" value={entityType} onChange={(e) => setView({ entity: e.target.value, offset: "0" })}>
              <option value="">All entities</option>
              {ENTITY_TYPES.map((t) => (
                <option key={t} value={t}>{t.replace(/_/g, " ")}</option>
              ))}
            </select>
          </div>
          <div className="spacer" />
          {events.data && <span className="muted" style={{ alignSelf: "flex-end", paddingBottom: 8 }}>{plural(events.data.total, "event")}, oldest first</span>}
        </div>
        <ErrorNotice error={events.error} />
        {events.loading && !events.data && <Skeleton lines={8} />}
        {events.data && events.data.items.length === 0 && <Empty icon={ScrollText} title="No events match">Change the filters to see more of the trail.</Empty>}
        {events.data && events.data.items.length > 0 && (
          <>
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th style={{ width: 28 }} />
                    <th className="right">#</th>
                    <th>When</th>
                    <th>Event</th>
                    <th>Actor</th>
                    <th>Entity</th>
                  </tr>
                </thead>
                <tbody>
                  {events.data.items.map((e) => {
                    const d = describeEvent(e);
                    const open = expanded === e.id;
                    return (
                      <Fragment key={e.id}>
                        <tr className="clickable" onClick={() => setExpanded(open ? null : e.id)} aria-expanded={open}>
                          <td className="faint">{open ? <ChevronDown width={14} height={14} /> : <ChevronRight width={14} height={14} />}</td>
                          <td className="right faint num">{e.id}</td>
                          <td className="nowrap muted">{when(e.occurred_at)}</td>
                          <td className="nowrap">
                            <span className="row" style={{ gap: 8, flexWrap: "nowrap" }}>
                              <span className={`activity-icon ${d.tone ?? ""}`} style={{ width: 24, height: 24 }} aria-hidden><d.icon /></span>
                              <span>
                                <strong style={{ color: "var(--ink)", fontWeight: 550 }}>{d.text}</strong>
                                <div className="faint mono" style={{ fontSize: 12 }}>{e.event_type}</div>
                              </span>
                            </span>
                          </td>
                          <td className="nowrap">{e.actor_kind === "SYSTEM" ? <span className="muted">System</span> : <code className="faint">{e.actor_user_id?.slice(0, 8)}</code>}</td>
                          <td className="nowrap">{e.entity_type.replace(/_/g, " ")} <code className="faint">{e.entity_id.slice(0, 13)}</code></td>
                        </tr>
                        {open && (
                          <tr>
                            <td />
                            <td colSpan={5} className="wrap">
                              <pre className="mono" style={{ margin: 0, padding: 10, background: "var(--surface-2)", border: "1px solid var(--border)", borderRadius: 6, whiteSpace: "pre-wrap", overflowWrap: "anywhere", fontSize: 13 }}>
                                {JSON.stringify({ entity_id: e.entity_id, dataset_version_id: e.dataset_version_id, payload: e.payload }, null, 2)}
                              </pre>
                            </td>
                          </tr>
                        )}
                      </Fragment>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <Pager offset={offset} size={PAGE_SIZE} total={events.data.total} onChange={setOffset} />
          </>
        )}
      </Card>
    </>
  );
}
