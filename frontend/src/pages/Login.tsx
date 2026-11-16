import { useState, type FormEvent } from "react";
import { type ApiError } from "../api";
import { useAuth } from "../auth";
import { ErrorBox, toApiError } from "../ui";

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
    <div className="login card">
      <h1>Sentinel</h1>
      <p className="muted">Can we publish this dataset, and what evidence supports that decision?</p>
      <ErrorBox error={error} />
      <form onSubmit={submit}>
        <div className="field">
          <label htmlFor="username">Username</label>
          <input id="username" autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} required />
        </div>
        <div className="field">
          <label htmlFor="password">Password</label>
          <input id="password" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required />
        </div>
        <button className="primary" type="submit" disabled={busy}>
          {busy ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </div>
  );
}
