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

// Multipart upload with real progress: XMLHttpRequest reports the bytes actually sent, which
// fetch cannot. Errors are parsed exactly as in request().
export interface UploadProgress {
  loaded: number;
  total: number;
  // True once every byte is sent and the server is checking and storing the files.
  sent: boolean;
}

function upload<T>(path: string, form: FormData, onProgress?: (p: UploadProgress) => void): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", BASE + path);
    xhr.withCredentials = true;
    if (csrfToken) xhr.setRequestHeader("X-CSRF-Token", csrfToken);
    xhr.upload.onprogress = (e) => onProgress?.({ loaded: e.loaded, total: e.lengthComputable ? e.total : 0, sent: false });
    xhr.upload.onload = () => onProgress?.({ loaded: 1, total: 1, sent: true });
    xhr.onerror = () => reject(new ApiError(0, "NETWORK_ERROR", "The server could not be reached."));
    xhr.onload = () => {
      let data: { error?: { code?: string; message?: string; details?: Record<string, unknown> } } | null = null;
      try {
        data = JSON.parse(xhr.responseText);
      } catch {
        data = null;
      }
      if (xhr.status >= 200 && xhr.status < 300) return resolve(data as T);
      const error = data?.error ?? {};
      if (xhr.status === 401) onUnauthenticated?.();
      reject(new ApiError(xhr.status, error.code ?? "HTTP_ERROR", error.message ?? `Request failed (${xhr.status}).`, error.details ?? {}));
    };
    xhr.send(form);
  });
}

export const api = {
  get: <T>(path: string) => request<T>("GET", path),
  upload,
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
  publication_ref?: string | null;
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

// ---- review and publication ---------------------------------------------------------------
export interface Person {
  id: string;
  display_name: string;
}

export interface Issue {
  id: string;
  finding_id: string;
  run_id: string;
  dataset_version_id: string;
  rule_id: string;
  severity: "BLOCKING" | "WARNING";
  waivable: boolean;
  state: "OPEN" | "WAIVER_REQUESTED" | "WAIVED" | "CLOSED_NOT_CURRENT";
  allowed_transitions: string[];
  state_changed_at: string;
  message?: string;
  failing_count?: number;
}

export interface Waiver {
  id: string;
  issue_id: string;
  rule_id: string;
  status: "REQUESTED" | "GRANTED" | "DENIED" | "STALE";
  stale_reason: string | null;
  category: string;
  justification: string;
  requested_by: Person | null;
  requested_at: string;
  decision: string | null;
  decided_by: Person | null;
  decided_at: string | null;
  comment: string | null;
}

export interface Note {
  id: string;
  author: Person | null;
  body: string;
  created_at: string;
}

export interface IssueDetail {
  issue: Issue;
  finding: Finding;
  notes: Note[];
  waivers: Waiver[];
}

export interface ReviewRequest {
  id: string;
  status: "OPEN" | "APPROVED" | "REJECTED" | "STALE";
  stale_reason: string | null;
  note: string;
  submitted_by: Person | null;
  submitted_at: string;
  decision: string | null;
  decided_by: Person | null;
  decided_at: string | null;
  comment: string | null;
  acknowledged_warning_count: number | null;
}

export interface EligibilityCheck {
  id: string;
  passed: boolean;
  code: string | null;
  details: Record<string, unknown>;
}

export interface Eligibility {
  eligible: boolean;
  checks: EligibilityCheck[];
}

export interface ReviewSummary {
  version: Version & { publication_ref: string | null };
  current_run_id: string | null;
  request: ReviewRequest | null;
  differences: string[];
  issues: Issue[];
  waivers: Waiver[];
  history: ReviewRequest[];
  open_warning_count: number;
  blocking_unwaived_count: number;
  blocking_non_waivable_count: number;
  live: { impact_totals: ImpactTotal[]; kpis: KpiRow[] } | null;
  eligibility: Eligibility;
}

export interface Publication {
  publication_ref: string;
  dataset: string;
  period: string;
  version_id: string;
  version_label: string;
  status: string;
  published_by: Person;
  published_at: string;
  snapshot_format: string;
  snapshot_hash: string;
  table_hashes: Record<string, string>;
  row_counts: Record<string, number>;
  manifest_sha256: string;
}

export interface Verification {
  result: "VERIFIED" | "FAILED";
  tables: { table: string; expected_sha256: string; actual_sha256: string; rows_expected: number; rows_actual: number }[];
  snapshot_hash_ok: boolean;
  manifest_sha256_ok: boolean;
}
