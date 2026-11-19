import { CheckCircle2, Download, FileCheck2, FileJson, ShieldCheck, ShieldX, XCircle } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ApiError, api, type Page, type Publication, type Verification } from "../api";
import { DataTable } from "../components/DataTable";
import { Badge, Card, Empty, ErrorNotice, Hash, Kpi, Money, Notice, PageHeader, PageLoading, Skeleton } from "../components/ui";
import { CATEGORY_LABELS, count, toApiError, useLoad, when } from "../lib";

interface Manifest {
  validation_run: { reference_date: string; finding_counts: Record<string, number> };
  issues: { rule_id: string; severity: string; final_state: string }[];
  waivers: { category: string; justification: string; requested_by: { display_name: string }; decided_by: { display_name: string } }[];
  review: { submitted_by: { display_name: string }; decided_by: { display_name: string }; decided_at: string; note: string; comment: string | null; acknowledged_warning_count: number };
  policy: Record<string, unknown>;
  impact_totals: { category: string; currency: string; amount: string; record_count: number }[];
}

export function PublicationsPage() {
  const navigate = useNavigate();
  const list = useLoad(() => api.get<Page<Publication>>("/publications"), []);
  return (
    <>
      <PageHeader title="Publications" subtitle="Immutable, hash-sealed snapshots of approved versions. One per reporting period." />
      <Card title="Publication history" subtitle={list.data ? `${list.data.total} publication${list.data.total === 1 ? "" : "s"}` : undefined} flush>
        <ErrorNotice error={list.error} />
        {list.loading && !list.data && <Skeleton lines={4} />}
        {list.data && (
          <DataTable
            rows={list.data.items}
            rowKey={(p) => p.publication_ref}
            onRowClick={(p) => navigate(`/publications/${p.publication_ref}`)}
            empty={<Empty icon={FileCheck2} title="Nothing has been published yet">A version can be published once it is validated, its blockers are resolved and a second person has approved it.</Empty>}
            columns={[
              { key: "ref", header: "Publication", className: "nowrap", render: (p) => <Link to={`/publications/${p.publication_ref}`} className="mono" onClick={(e) => e.stopPropagation()}>{p.publication_ref}</Link> },
              { key: "period", header: "Period", className: "strong", render: (p) => p.period },
              { key: "version", header: "Version", className: "nowrap", render: (p) => <Link to={`/versions/${p.version_id}`} className="mono" onClick={(e) => e.stopPropagation()}>{p.version_label}</Link> },
              { key: "rows", header: "Invoices", align: "right", render: (p) => count(p.row_counts.invoices) },
              { key: "by", header: "Published", className: "nowrap", render: (p) => <span className="muted">{when(p.published_at)} · {p.published_by.display_name}</span> },
              { key: "status", header: "Status", render: () => <Badge tone="ok" dot>Sealed</Badge> },
              { key: "hash", header: "Snapshot hash", render: (p) => <code className="faint">{p.snapshot_hash.slice(0, 12)}…</code> },
            ]}
          />
        )}
      </Card>
    </>
  );
}

export function PublicationPage() {
  const { ref = "" } = useParams();
  const publication = useLoad(() => api.get<Publication>(`/publications/${ref}`), [ref]);
  const manifest = useLoad(() => api.get<Manifest>(`/publications/${ref}/manifest`), [ref]);
  const [verification, setVerification] = useState<Verification | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);

  async function verify() {
    setBusy(true);
    setError(null);
    try {
      setVerification(await api.post<Verification>(`/publications/${ref}/verify`));
    } catch (err) {
      setError(toApiError(err));
    } finally {
      setBusy(false);
    }
  }

  const p = publication.data;
  if (publication.loading && !p) return <PageLoading />;
  if (!p) return <ErrorNotice error={publication.error} />;
  const m = manifest.data;
  const verified = verification?.result === "VERIFIED";

  return (
    <>
      <PageHeader
        crumbs={[{ label: "Publications", to: "/publications" }, { label: p.publication_ref }]}
        title={<span className="mono" style={{ fontSize: "inherit" }}>{p.publication_ref}</span>}
        badge={<Badge tone="ok" dot>Sealed</Badge>}
        subtitle={<>{p.dataset} {p.period} · <Link to={`/versions/${p.version_id}`} className="mono">{p.version_label}</Link> · published {when(p.published_at)} by {p.published_by.display_name}</>}
        actions={
          <>
            <a className="btn" href={api.url(`/publications/${p.publication_ref}/manifest`)} target="_blank" rel="noreferrer">
              <FileJson aria-hidden />
              Manifest
            </a>
            <a className="btn" href={api.url(`/publications/${p.publication_ref}/export`)}>
              <Download aria-hidden />
              Export ZIP
            </a>
            <button className="btn primary" onClick={() => void verify()} disabled={busy}>
              <ShieldCheck aria-hidden />
              {busy ? "Verifying…" : "Verify"}
            </button>
          </>
        }
      />
      <div className="stack">
        <ErrorNotice error={error} />
        {verification && (
          <Notice tone={verified ? "ok" : "error"} title={verified ? "VERIFIED" : "FAILED"} role="status">
            Table hashes {verification.tables.every((t) => t.expected_sha256 === t.actual_sha256) ? "match" : "differ"}, the snapshot hash {verification.snapshot_hash_ok ? "matches" : "differs"} and the manifest hash {verification.manifest_sha256_ok ? "matches" : "differs"}. Recomputed from the stored snapshot just now.
          </Notice>
        )}
        <div className="kpis" style={{ marginBottom: 0 }}>
          <Kpi label="Invoices published" value={count(p.row_counts.invoices)} icon={FileCheck2} />
          <Kpi label="Suppliers published" value={count(p.row_counts.suppliers)} icon={FileCheck2} />
          <Kpi label="Waivers in the record" value={m ? m.waivers.length : "—"} icon={ShieldCheck} hint="Granted, bound to this exact data" />
          <Kpi label="Warnings acknowledged" value={m ? m.review.acknowledged_warning_count : "—"} icon={ShieldCheck} hint={m ? `by ${m.review.decided_by.display_name}` : undefined} />
        </div>
        <div className="split-wide">
          <Card title="Snapshot evidence" subtitle="Anyone can recompute these from the export with scripts/verify_publication.py.">
            <dl className="props">
              <dt>Snapshot format</dt>
              <dd><code>{p.snapshot_format}</code></dd>
              <dt>Snapshot hash</dt>
              <dd><Hash value={p.snapshot_hash} length={28} /></dd>
              <dt>Manifest SHA-256</dt>
              <dd><Hash value={p.manifest_sha256} length={28} /></dd>
              {Object.entries(p.table_hashes).map(([table, hash]) => {
                const check = verification?.tables.find((t) => t.table === table);
                return (
                  <div key={table} style={{ display: "contents" }}>
                    <dt>{table}.csv · {count(p.row_counts[table])} rows</dt>
                    <dd className="row" style={{ gap: 6, flexWrap: "nowrap" }}>
                      <Hash value={hash} length={28} />
                      {check && (check.expected_sha256 === check.actual_sha256 && check.rows_expected === check.rows_actual ? <CheckCircle2 width={16} height={16} className="text-ok" aria-label="Matches" /> : <XCircle width={16} height={16} className="text-danger" aria-label="Differs" />)}
                    </dd>
                  </div>
                );
              })}
            </dl>
          </Card>
          <Card title="Approval record" subtitle="From the manifest stored with the publication">
            {manifest.loading && !m && <Skeleton lines={4} />}
            {m && (
              <dl className="props" style={{ gridTemplateColumns: "minmax(110px, 140px) minmax(0, 1fr)" }}>
                <dt>Submitted by</dt>
                <dd>{m.review.submitted_by.display_name}</dd>
                <dt>Approved by</dt>
                <dd>{m.review.decided_by.display_name} · {when(m.review.decided_at)}</dd>
                <dt>Note</dt>
                <dd>{m.review.note}</dd>
                {m.review.comment && (
                  <>
                    <dt>Comment</dt>
                    <dd>{m.review.comment}</dd>
                  </>
                )}
                <dt>Policy</dt>
                <dd className="pill-list">
                  <Badge tone="neutral">{String(m.policy.required_approvals)} approval</Badge>
                  <Badge tone="neutral">no self-approval</Badge>
                  <Badge tone="neutral">one publication per period</Badge>
                </dd>
              </dl>
            )}
          </Card>
        </div>
        {m && (
          <div className="grid-2">
            <Card title="Issues at publication" subtitle={`Reference date ${m.validation_run.reference_date}`} flush>
              <DataTable
                rows={m.issues}
                rowKey={(i) => i.rule_id}
                empty={<Empty compact title="Published with no issues" icon={ShieldCheck} />}
                columns={[
                  { key: "rule", header: "Rule", className: "nowrap", render: (i) => <span className="rule-id">{i.rule_id}</span> },
                  { key: "sev", header: "Severity", render: (i) => <Badge tone={i.severity === "BLOCKING" ? "danger" : "warn"} square>{i.severity === "BLOCKING" ? "Blocking" : "Warning"}</Badge> },
                  { key: "state", header: "Final state", className: "nowrap", render: (i) => (i.final_state === "WAIVED" ? <Badge tone="ok">Waived</Badge> : i.severity === "WARNING" ? <Badge tone="neutral">Acknowledged</Badge> : <Badge tone="neutral">{i.final_state.toLowerCase()}</Badge>) },
                ]}
              />
            </Card>
            <Card title="Impact at publication" flush>
              <DataTable
                rows={m.impact_totals}
                rowKey={(t) => t.category + t.currency}
                empty={<Empty compact title="No financial impact" icon={ShieldX} />}
                columns={[
                  { key: "cat", header: "Category", className: "nowrap", render: (t) => <Badge tone={t.category === "CONFIRMED_DISCREPANCY" ? "danger" : "warn"}>{CATEGORY_LABELS[t.category]}</Badge> },
                  { key: "amt", header: "Amount", align: "right", render: (t) => <Money amount={t.amount} currency={t.currency} /> },
                  { key: "n", header: "Records", align: "right", render: (t) => t.record_count },
                ]}
              />
            </Card>
          </div>
        )}
      </div>
    </>
  );
}
