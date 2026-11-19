import { BadgeCheck, Fingerprint, Scale } from "lucide-react";
import { useState, type FormEvent } from "react";
import { type ApiError } from "../api";
import { useAuth } from "../auth";
import { BrandMark } from "../components/Shell";
import { ErrorNotice } from "../components/ui";
import { toApiError } from "../lib";

export function LoginPage() {
  const { signIn } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await signIn(username, password);
    } catch (err) {
      setError(toApiError(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="auth">
      <section className="auth-panel">
        <div className="brand" style={{ padding: 0 }}>
          <BrandMark />
          <div>
            <div className="brand-name">Sentinel</div>
            <div className="brand-sub">Data quality gate</div>
          </div>
        </div>
        <div>
          <h2>Can we publish this dataset, and what evidence supports that decision?</h2>
          <p>Every reporting period is validated, quantified and approved by a second person before it can be published.</p>
          <div className="auth-points">
            <div className="auth-point">
              <Scale aria-hidden />
              <div>
                <strong>Deterministic validation</strong>
                32 rules over every invoice, with exact record-level evidence.
              </div>
            </div>
            <div className="auth-point">
              <BadgeCheck aria-hidden />
              <div>
                <strong>Financial impact you can defend</strong>
                Confirmed discrepancies and potential exposure, per currency.
              </div>
            </div>
            <div className="auth-point">
              <Fingerprint aria-hidden />
              <div>
                <strong>Verifiable publications</strong>
                Immutable, hash-sealed snapshots with a full audit trail.
              </div>
            </div>
          </div>
        </div>
        <div className="brand-sub">Supplier invoices · monthly close</div>
      </section>
      <div className="auth-form-wrap">
        <form className="auth-form" onSubmit={submit}>
          <div>
            <h1>Sign in</h1>
            <p className="muted" style={{ marginTop: 4 }}>
              Use your Sentinel account.
            </p>
          </div>
          <ErrorNotice error={error} />
          <div className="field">
            <label className="field-label" htmlFor="username">
              Username
            </label>
            <input id="username" className="input" autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} required autoFocus />
          </div>
          <div className="field">
            <label className="field-label" htmlFor="password">
              Password
            </label>
            <input id="password" className="input" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required />
          </div>
          <button className="btn primary block" type="submit" disabled={busy} style={{ height: 38 }}>
            {busy ? "Signing in…" : "Sign in"}
          </button>
        </form>
      </div>
    </div>
  );
}
