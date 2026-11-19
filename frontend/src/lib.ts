// Hooks and formatting shared by every screen. No data is computed here: values are only
// formatted for display.
import { useCallback, useEffect, useState } from "react";
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

export function when(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

export function day(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString(undefined, { dateStyle: "medium" });
}

export function ago(iso: string | null | undefined): string {
  if (!iso) return "—";
  const seconds = Math.round((Date.now() - new Date(iso).getTime()) / 1000);
  if (seconds < 45) return "just now";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  const days = Math.round(hours / 24);
  if (days < 30) return `${days} d ago`;
  return day(iso);
}

export function short(hash: string, length = 12): string {
  return hash.length > length ? `${hash.slice(0, length)}…` : hash;
}

export function count(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : value.toLocaleString("en-GB");
}

// Decimal strings from the API are formatted without floating-point arithmetic.
export function groupDigits(amount: string): string {
  const negative = amount.startsWith("-");
  const [whole, fraction = "00"] = amount.replace("-", "").split(".");
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return `${negative ? "−" : ""}${grouped}.${fraction.padEnd(2, "0").slice(0, 2)}`;
}

// Compact display for charts and KPI cards only (for example 1.24M). Labels always also
// carry the exact value where the precise figure matters.
export function compact(amount: string | number): string {
  const value = typeof amount === "number" ? amount : Number(amount);
  const abs = Math.abs(value);
  const sign = value < 0 ? "−" : "";
  if (abs >= 1e9) return `${sign}${(abs / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `${sign}${(abs / 1e6).toFixed(2)}M`;
  if (abs >= 1e4) return `${sign}${(abs / 1e3).toFixed(1)}K`;
  return `${sign}${abs.toLocaleString("en-GB", { maximumFractionDigits: 2 })}`;
}

export function plural(n: number, one: string, many = `${one}s`): string {
  return `${n.toLocaleString("en-GB")} ${n === 1 ? one : many}`;
}

export function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join("");
}

export const CATEGORY_LABELS: Record<string, string> = {
  CONFIRMED_DISCREPANCY: "Confirmed discrepancy",
  POTENTIAL_EXPOSURE: "Potential exposure",
};

export const CATEGORY_NOTES: Record<string, string> = {
  CONFIRMED_DISCREPANCY: "A misstatement the dataset alone proves, with an exact value.",
  POTENTIAL_EXPOSURE: "The value of records whose correct treatment cannot be determined.",
};

export const KPI_NAMES: Record<string, string> = {
  "KPI-01": "Total invoiced spend",
  "KPI-02": "Spend by supplier",
  "KPI-03": "Invoice count",
  "KPI-04": "Unattributed spend",
};
