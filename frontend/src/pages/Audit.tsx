import { useState } from "react";
import { api, type AuditEvent, type Page } from "../api";
import { Card, Empty, ErrorBox, Loading, useLoad, when } from "../ui";

const PAGE_SIZE = 50;

export function AuditPage() {
  const [eventType, setEventType] = useState("");
  const [entityType, setEntityType] = useState("");
  const [offset, setOffset] = useState(0);
  const query = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String(offset) });
  if (eventType) query.set("event_type", eventType.trim().toUpperCase());
  if (entityType) query.set("entity_type", entityType.trim());
  const events = useLoad(() => api.get<Page<AuditEvent>>(`/audit/events?${query}`), [query.toString()]);
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Audit trail</h1>
          <p className="muted">Append-only. Every state change is recorded in the same transaction as the change.</p>
        </div>
      </div>
      <Card>
        <div className="row">
          <div className="field">
            <label htmlFor="event-type">Event type</label>
            <input id="event-type" placeholder="e.g. VERSION_CREATED" value={eventType} onChange={(e) => { setEventType(e.target.value); setOffset(0); }} />
          </div>
          <div className="field">
            <label htmlFor="entity-type">Entity type</label>
            <input id="entity-type" placeholder="e.g. dataset_version" value={entityType} onChange={(e) => { setEntityType(e.target.value); setOffset(0); }} />
          </div>
        </div>
        <ErrorBox error={events.error} />
        {events.loading && !events.data && <Loading />}
        {events.data && events.data.items.length === 0 && <Empty>No events match.</Empty>}
        {events.data && events.data.items.length > 0 && (
          <>
            <div className="scroll">
              <table>
                <thead>
                  <tr>
                    <th className="num">#</th>
                    <th>When</th>
                    <th>Actor</th>
                    <th>Event</th>
                    <th>Entity</th>
                    <th>Detail</th>
                  </tr>
                </thead>
                <tbody>
                  {events.data.items.map((e) => (
                    <tr key={e.id}>
                      <td className="num">{e.id}</td>
                      <td style={{ whiteSpace: "nowrap" }}>{when(e.occurred_at)}</td>
                      <td>{e.actor_kind === "SYSTEM" ? "System" : <span className="mono">{e.actor_user_id?.slice(0, 8)}</span>}</td>
                      <td className="mono">{e.event_type}</td>
                      <td>
                        {e.entity_type} <span className="mono muted">{e.entity_id.slice(0, 13)}</span>
                      </td>
                      <td className="mono" style={{ maxWidth: 420, overflowWrap: "anywhere" }}>{JSON.stringify(e.payload)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="pager">
              <span>
                {offset + 1}–{offset + events.data.items.length} of {events.data.total}
              </span>
              <button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>
                Previous
              </button>
              <button disabled={offset + PAGE_SIZE >= events.data.total} onClick={() => setOffset(offset + PAGE_SIZE)}>
                Next
              </button>
            </div>
          </>
        )}
      </Card>
    </>
  );
}
