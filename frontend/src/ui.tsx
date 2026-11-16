import { useCallback, useEffect, useState, type ReactNode } from "react";
import { ApiError } from "./api";

export function useLoad<T>(load: () => Promise<T>, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const run = useCallback(load, deps);
  useEffect(() => {
    let live = true;
    setLoading(true);
    run()
      .then((value) => {
        if (live) {
          setData(value);
          setError(null);
        }
      })
      .catch((err) => live && setError(toApiError(err)))
      .finally(() => live && setLoading(false));
    return () => {
      live = false;
    };
  }, [run, tick]);
  return { data, error, loading, reload: () => setTick((t) => t + 1) };
}

export function toApiError(err: unknown): ApiError {
  return err instanceof ApiError ? err : new ApiError(0, "NETWORK_ERROR", "The server could not be reached.");
}

export function ErrorBox({ error }: { error: ApiError | null }) {
  if (!error) return null;
  return (
    <div className="alert error" role="alert">
      <strong>{error.code}</strong> {error.message}
    </div>
  );
}

export function Loading({ what = "Loading" }: { what?: string }) {
  return <p className="muted">{what}…</p>;
}

const STATE_LABELS: Record<string, string> = {
  NO_DATA: "No data",
  INGESTED: "Ingested, not validated",
  VALIDATING: "Validating",
  VALIDATION_FAILED: "Validation failed",
  VALIDATED: "Validated",
  IN_REVIEW: "In review",
  APPROVED: "Approved",
  PUBLISHED: "Published",
  SUPERSEDED: "Superseded",
};

export function StateBadge({ state }: { state: string }) {
  return <span className={`badge state-${state.toLowerCase()}`}>{STATE_LABELS[state] ?? state}</span>;
}

// Severity and category are always shown as text, never by colour alone (FR-016).
export function Severity({ value }: { value: string }) {
  return <span className={`badge sev-${value.toLowerCase()}`}>{value}</span>;
}

export const CATEGORY_LABELS: Record<string, string> = {
  CONFIRMED_DISCREPANCY: "Confirmed discrepancy",
  POTENTIAL_EXPOSURE: "Potential exposure",
};

export function Money({ amount, currency }: { amount: string | null; currency: string | null }) {
  if (amount === null) return <span className="muted">not quantifiable</span>;
  const [whole, fraction] = amount.split(".");
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return (
    <span className="money">
      {grouped}.{fraction ?? "00"} <span className="currency">{currency || "(no currency)"}</span>
    </span>
  );
}

export function when(iso: string | null): string {
  if (!iso) return "—";
  const date = new Date(iso);
  return date.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

export function short(hash: string, length = 12): string {
  return hash.length > length ? `${hash.slice(0, length)}…` : hash;
}

export function Card({ title, actions, children }: { title?: ReactNode; actions?: ReactNode; children: ReactNode }) {
  return (
    <section className="card">
      {(title || actions) && (
        <header className="card-head">
          {title && <h2>{title}</h2>}
          {actions && <div className="actions">{actions}</div>}
        </header>
      )}
      {children}
    </section>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="empty">{children}</p>;
}
