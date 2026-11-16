import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ApiError, api, type Page, type Publication, type Verification } from "../api";
import { Card, Empty, ErrorBox, Loading, short, toApiError, useLoad, when } from "../ui";

export function PublicationsPage() {
  const list = useLoad(() => api.get<Page<Publication>>("/publications"), []);
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Publications</h1>
          <p className="muted">Immutable snapshots of approved versions. One per reporting period.</p>
        </div>
      </div>
      <Card>
        <ErrorBox error={list.error} />
        {list.loading && !list.data && <Loading />}
        {list.data && list.data.items.length === 0 && <Empty>Nothing has been published yet.</Empty>}
        {list.data && list.data.items.length > 0 && (
          <table>
            <thead>
              <tr>
                <th>Publication</th>
                <th>Period</th>
                <th>Version</th>
                <th>Published</th>
                <th>Snapshot hash</th>
              </tr>
            </thead>
            <tbody>
              {list.data.items.map((p) => (
                <tr key={p.publication_ref}>
                  <td>
                    <Link to={`/publications/${p.publication_ref}`}>{p.publication_ref}</Link>
                  </td>
                  <td>{p.period}</td>
                  <td>
                    <Link to={`/versions/${p.version_id}`}>{p.version_label}</Link>
                  </td>
                  <td>
                    {when(p.published_at)} by {p.published_by.display_name}
                  </td>
                  <td className="mono">{short(p.snapshot_hash, 16)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </>
  );
}

export function PublicationPage() {
  const { ref = "" } = useParams();
  const publication = useLoad(() => api.get<Publication>(`/publications/${ref}`), [ref]);
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
  return (
    <>
      <div className="crumbs">
        <Link to="/publications">Publications</Link> / {ref}
      </div>
      <ErrorBox error={publication.error ?? error} />
      {publication.loading && !p && <Loading />}
      {p && (
        <>
          <div className="page-head">
            <div>
              <h1>{p.publication_ref}</h1>
              <p className="muted">
                {p.dataset} {p.period} · <Link to={`/versions/${p.version_id}`}>{p.version_label}</Link> · published {when(p.published_at)} by {p.published_by.display_name}
              </p>
            </div>
            <div className="actions">
              <a className="button" href={api.url(`/publications/${p.publication_ref}/manifest`)} target="_blank" rel="noreferrer">
                Manifest
              </a>
              <a className="button" href={api.url(`/publications/${p.publication_ref}/export`)}>
                Export ZIP
              </a>
              <button className="primary" onClick={() => void verify()} disabled={busy}>
                {busy ? "Verifying…" : "Verify"}
              </button>
            </div>
          </div>
          {verification && (
            <div className={`alert ${verification.result === "VERIFIED" ? "ok" : "error"}`}>
              <strong>{verification.result}</strong> — table hashes {verification.tables.every((t) => t.expected_sha256 === t.actual_sha256) ? "match" : "DIFFER"}, snapshot hash{" "}
              {verification.snapshot_hash_ok ? "matches" : "DIFFERS"}, manifest hash {verification.manifest_sha256_ok ? "matches" : "DIFFERS"}.
            </div>
          )}
          <Card title="Evidence">
            <dl className="facts">
              <dt>Snapshot format</dt>
              <dd>{p.snapshot_format}</dd>
              <dt>Snapshot hash</dt>
              <dd className="mono">{p.snapshot_hash}</dd>
              <dt>Manifest SHA-256</dt>
              <dd className="mono">{p.manifest_sha256}</dd>
              {Object.entries(p.table_hashes).map(([table, hash]) => (
                <div key={table} style={{ display: "contents" }}>
                  <dt>
                    {table}.csv ({p.row_counts[table]?.toLocaleString()} rows)
                  </dt>
                  <dd className="mono">{hash}</dd>
                </div>
              ))}
            </dl>
            <p className="muted">
              The export contains the manifest, both CSV files and verification instructions. It can be checked offline with <span className="mono">scripts/verify_publication.py</span>.
            </p>
          </Card>
        </>
      )}
    </>
  );
}
