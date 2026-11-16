// Thin client for the Sentinel API. The frontend computes no eligibility and no impact:
// it only displays what the backend returns.

export const DATASET = "SUPINV";
const BASE = "/api/v1";

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public details: Record<string, unknown> = {},
  ) {
    super(message);
  }
}

let csrfToken: string | null = null;
let onUnauthenticated: (() => void) | null = null;

export function setCsrfToken(token: string | null) {
  csrfToken = token;
}

export function setUnauthenticatedHandler(handler: () => void) {
  onUnauthenticated = handler;
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = {};
  let payload: BodyInit | undefined;
  if (body instanceof FormData) {
    payload = body;
  } else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }
  if (method !== "GET" && csrfToken) headers["X-CSRF-Token"] = csrfToken;
  const response = await fetch(BASE + path, {
    method,
    headers,
    body: payload,
    credentials: "same-origin",
  });
  if (response.status === 204) return undefined as T;
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const error = data?.error ?? {};
    if (response.status === 401 && path !== "/auth/login") onUnauthenticated?.();
    throw new ApiError(
      response.status,
      error.code ?? "HTTP_ERROR",
      error.message ?? `Request failed (${response.status}).`,
      error.details ?? {},
    );
  }
  return data as T;
}

export const api = {
  get: <T>(path: string) => request<T>("GET", path),
  post: <T>(path: string, body?: unknown) => request<T>("POST", path, body),
  patch: <T>(path: string, body?: unknown) => request<T>("PATCH", path, body),
  url: (path: string) => BASE + path,
};

// ---- response shapes (Doc 4 §3) ---------------------------------------------------------
export type Role = "ANALYST" | "APPROVER" | "ADMIN";

export interface Session {
  user: { id: string; username: string; display_name: string };
  roles: Role[];
  csrf_token: string;
}

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface Counts {
  BLOCKING: number;
  WARNING: number;
  INFO: number;
}

export interface Version {
  id: string;
  label: string;
  dataset_key: string;
  period: string;
  seq: number;
  status: "ACTIVE" | "SUPERSEDED";
  derived_state: string;
  content_hash: string;
  hash_algorithm: string;
  columns: Record<string, string[]>;
  row_counts: Record<string, number>;
  created_by: { id: string; display_name: string };
  created_at: string;
  finding_counts: Counts;
}

export interface PeriodRow {
  period: string;
  derived_state: string;
  current_version: Version | null;
  blocking_count: number;
  warning_count: number;
}

export interface Attempt {
  id: string;
  status: "SUCCEEDED" | "FAILED" | "DUPLICATE_CONTENT";
  started_at: string;
  files: { table: string; filename: string; sha256: string; size_bytes: number; rows: number | null }[];
  errors: { errors?: { table: string; line: number; code: string }[]; total?: number; code?: string } | null;
  dataset_version_id: string | null;
}

export interface PeriodDetail {
  period: string;
  versions: Version[];
  ingestion_attempts: Attempt[];
}

export interface Run {
  id: string;
  dataset_version_id: string;
  rule_set_version_id: string;
  engine_version: string;
  period: string;
  reference_date: string;
  status: "RUNNING" | "COMPLETED" | "ERROR";
  is_current: boolean;
  finding_counts: Counts | null;
  not_evaluated: { rule_id: string; missing_columns: string[] }[];
  error_detail: { type: string; rule_id: string | null } | null;
  started_at: string;
  finished_at: string | null;
}

export interface Finding {
  id: string;
  run_id: string;
  rule_id: string;
  rule_type: string;
  severity: "BLOCKING" | "WARNING" | "INFO";
  waivable: boolean;
  table: string;
  columns: string[];
  failing_count: number;
  evaluated_count: number;
  truncated: boolean;
  samples: { row_num: number; values: Record<string, string | null> }[];
  message: string;
  details: Record<string, unknown>;
}

export interface FindingRecord {
  row_num: number;
  record_key: string;
  group_no: number | null;
  is_canonical: boolean | null;
  cells: Record<string, string | null>;
  failing_columns: string[];
}

export interface ImpactTotal {
  category: string;
  currency: string;
  amount: string;
  record_count: number;
  unquantifiable_count: number;
}

export interface KpiRow {
  kpi_id: string;
  currency: string;
  supplier_id: string | null;
  as_reported: string;
  fully_adjusted: string;
  delta_abs: string | null;
  delta_pct: string | null;
  direction: string | null;
  assumption: string | null;
}

export interface RunImpact {
  totals: ImpactTotal[];
  kpis: KpiRow[];
  supplier_ranking: KpiRow[];
  supplier_ranking_total: number;
}

export interface ImpactFigure {
  category: string;
  currency: string | null;
  amount: string | null;
  quantifiable: boolean;
  record_count: number;
  formula_id: string;
  assumption: string;
  inputs: Record<string, unknown>;
}

export interface KpiEffect {
  kpi_id: string;
  currency: string;
  supplier_id: string | null;
  value: string;
  delta_abs: string | null;
  delta_pct: string | null;
  direction: string | null;
  assumption: string | null;
}

export interface FindingImpact {
  figures: ImpactFigure[];
  kpi_effects: KpiEffect[];
}

export interface AuditEvent {
  id: number;
  occurred_at: string;
  actor_kind: string;
  actor_user_id: string | null;
  event_type: string;
  entity_type: string;
  entity_id: string;
  dataset_version_id: string | null;
  payload: Record<string, unknown>;
}

export interface UserRow {
  id: string;
  username: string;
  display_name: string;
  is_active: boolean;
  roles: Role[];
}
