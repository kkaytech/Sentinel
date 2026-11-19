import { AlertCircle, AlertTriangle, Check, CheckCircle2, ChevronRight, Copy, Info, Inbox, type LucideIcon } from "lucide-react";
import { useState, type ReactNode } from "react";
import { Link, NavLink } from "react-router-dom";
import type { ApiError } from "../api";
import { groupDigits } from "../lib";

// ---- Layout -------------------------------------------------------------------------------
export interface Crumb {
  label: string;
  to?: string;
}

export function PageHeader({
  title,
  badge,
  subtitle,
  crumbs,
  actions,
}: {
  title: ReactNode;
  badge?: ReactNode;
  subtitle?: ReactNode;
  crumbs?: Crumb[];
  actions?: ReactNode;
}) {
  return (
    <>
      {crumbs && crumbs.length > 0 && (
        <nav className="crumbs" aria-label="Breadcrumb">
          {crumbs.map((c, n) => (
            <span key={n} className="row" style={{ gap: 6 }}>
              {n > 0 && <ChevronRight aria-hidden />}
              {c.to ? <Link to={c.to}>{c.label}</Link> : <span>{c.label}</span>}
            </span>
          ))}
        </nav>
      )}
      <header className="page-head">
        <div className="page-head-main">
          <div className="page-title">
            <h1>{title}</h1>
            {badge}
          </div>
          {subtitle && <div className="page-sub">{subtitle}</div>}
        </div>
        {actions && <div className="page-actions">{actions}</div>}
      </header>
    </>
  );
}

export function Card({
  title,
  subtitle,
  actions,
  children,
  flush,
  footer,
  className,
}: {
  title?: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  flush?: boolean;
  footer?: ReactNode;
  className?: string;
}) {
  return (
    <section className={`card ${className ?? ""}`}>
      {(title || actions) && (
        <header className="card-head">
          <div className="card-head-text">
            {title && <h2>{title}</h2>}
            {subtitle && <div className="card-sub">{subtitle}</div>}
          </div>
          {actions && <div className="row" style={{ gap: 8 }}>{actions}</div>}
        </header>
      )}
      <div className={`card-body ${flush ? "flush" : ""}`}>{children}</div>
      {footer && <footer className="card-foot">{footer}</footer>}
    </section>
  );
}

export type Tone = "ok" | "warn" | "danger" | "info" | "accent" | "neutral";

export function Kpi({
  label,
  value,
  hint,
  icon: Icon,
  tone,
}: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  icon?: LucideIcon;
  tone?: Tone;
}) {
  return (
    <div className={`kpi ${tone ? `tone-${tone}` : ""}`}>
      <div className="kpi-top">
        <span className="kpi-label">{label}</span>
        {Icon && (
          <span className="kpi-icon" aria-hidden>
            <Icon />
          </span>
        )}
      </div>
      <div className="kpi-value">{value}</div>
      {hint && <div className="kpi-hint">{hint}</div>}
    </div>
  );
}

export function Tabs({ items }: { items: { to: string; label: string; icon?: LucideIcon; end?: boolean }[] }) {
  return (
    <nav className="tabs" aria-label="Sections">
      {items.map(({ to, label, icon: Icon, end }) => (
        <NavLink key={to} to={to} end={end}>
          {Icon && <Icon aria-hidden />}
          {label}
        </NavLink>
      ))}
    </nav>
  );
}

// ---- Status -------------------------------------------------------------------------------
export function Badge({ tone = "neutral", children, dot, square }: { tone?: Tone; children: ReactNode; dot?: boolean; square?: boolean }) {
  return (
    <span className={`badge ${tone} ${square ? "square" : ""}`}>
      {dot && <span className="dot" aria-hidden />}
      {children}
    </span>
  );
}

const STATES: Record<string, { label: string; tone: Tone }> = {
  NO_DATA: { label: "No data", tone: "neutral" },
  INGESTED: { label: "Ingested, not validated", tone: "info" },
  VALIDATING: { label: "Validating", tone: "warn" },
  VALIDATION_FAILED: { label: "Validation failed", tone: "danger" },
  VALIDATED: { label: "Validated", tone: "accent" },
  IN_REVIEW: { label: "In review", tone: "warn" },
  APPROVED: { label: "Approved", tone: "ok" },
  PUBLISHED: { label: "Published", tone: "ok" },
  SUPERSEDED: { label: "Superseded", tone: "neutral" },
};

export function StateBadge({ state }: { state: string }) {
  const s = STATES[state] ?? { label: state, tone: "neutral" as Tone };
  return (
    <Badge tone={s.tone} dot>
      {s.label}
    </Badge>
  );
}

// Severity and category are always text, never colour alone (FR-016).
export function Severity({ value }: { value: string }) {
  const tone: Tone = value === "BLOCKING" ? "danger" : value === "WARNING" ? "warn" : "info";
  return (
    <Badge tone={tone} square>
      {value === "BLOCKING" ? "Blocking" : value === "WARNING" ? "Warning" : "Info"}
    </Badge>
  );
}

export const ISSUE_STATES: Record<string, { label: string; tone: Tone }> = {
  OPEN: { label: "Open", tone: "danger" },
  WAIVER_REQUESTED: { label: "Waiver requested", tone: "warn" },
  WAIVED: { label: "Waived", tone: "ok" },
  CLOSED_NOT_CURRENT: { label: "Closed (run not current)", tone: "neutral" },
};

export function IssueState({ state, severity }: { state: string; severity?: string }) {
  if (severity === "WARNING" && state === "OPEN") return <Badge tone="warn">To acknowledge</Badge>;
  const s = ISSUE_STATES[state] ?? { label: state, tone: "neutral" as Tone };
  return <Badge tone={s.tone}>{s.label}</Badge>;
}

export function Money({ amount, currency, compactValue }: { amount: string | null; currency: string | null; compactValue?: string }) {
  if (amount === null) return <span className="muted">Not quantifiable</span>;
  return (
    <span className="money" title={compactValue ? `${groupDigits(amount)} ${currency ?? ""}` : undefined}>
      {compactValue ?? groupDigits(amount)}
      <span className="ccy">{currency || "(none)"}</span>
    </span>
  );
}

export function Hash({ value, length }: { value: string; length?: number }) {
  const [copied, setCopied] = useState(false);
  return (
    <span className="hash">
      <code title={value} data-value={value}>{length && value.length > length ? `${value.slice(0, length)}…` : value}</code>
      <button
        type="button"
        className="icon-btn copy"
        aria-label="Copy to clipboard"
        title={copied ? "Copied" : "Copy"}
        onClick={() => {
          void navigator.clipboard?.writeText(value).then(() => {
            setCopied(true);
            window.setTimeout(() => setCopied(false), 1400);
          });
        }}
      >
        {copied ? <Check /> : <Copy />}
      </button>
    </span>
  );
}

// ---- Feedback states ----------------------------------------------------------------------
const NOTICE_ICONS = { error: AlertCircle, warn: AlertTriangle, ok: CheckCircle2, info: Info };

export function Notice({ tone, title, children, role }: { tone: keyof typeof NOTICE_ICONS; title?: ReactNode; children?: ReactNode; role?: "alert" | "status" }) {
  const Icon = NOTICE_ICONS[tone];
  return (
    <div className={`notice ${tone}`} role={role}>
      <Icon aria-hidden />
      <div className="notice-body">
        {title && <div className="notice-title">{title}</div>}
        {children}
      </div>
    </div>
  );
}

export function ErrorNotice({ error }: { error: ApiError | null }) {
  if (!error) return null;
  return (
    <Notice tone="error" role="alert" title={error.message}>
      <span className="mono" style={{ opacity: 0.8 }}>
        {error.code}
      </span>
    </Notice>
  );
}

export function Empty({ title, children, icon: Icon = Inbox, compact, action }: { title?: string; children?: ReactNode; icon?: LucideIcon; compact?: boolean; action?: ReactNode }) {
  return (
    <div className={`empty ${compact ? "compact" : ""}`}>
      {!compact && (
        <span className="empty-icon" aria-hidden>
          <Icon />
        </span>
      )}
      {title && <div className="empty-title">{title}</div>}
      {children && <div>{children}</div>}
      {action}
    </div>
  );
}

export function Skeleton({ lines = 4 }: { lines?: number }) {
  return (
    <div className="loading-block" aria-busy="true" aria-label="Loading">
      {Array.from({ length: lines }, (_, n) => (
        <div key={n} className="skeleton" style={{ height: n === 0 ? 18 : 14, width: `${n === 0 ? 40 : 100 - ((n * 13) % 35)}%` }} />
      ))}
    </div>
  );
}

export function PageLoading() {
  return (
    <div className="stack" aria-busy="true">
      <div className="skeleton" style={{ height: 28, width: 280 }} />
      <div className="kpis">
        {[0, 1, 2, 3].map((n) => (
          <div key={n} className="kpi">
            <div className="skeleton" style={{ height: 12, width: "50%" }} />
            <div className="skeleton" style={{ height: 24, width: "40%", marginTop: 12 }} />
          </div>
        ))}
      </div>
      <div className="card">
        <Skeleton lines={6} />
      </div>
    </div>
  );
}

// ---- Filters ------------------------------------------------------------------------------
export function Segmented<T extends string>({
  options,
  value,
  onChange,
  label,
}: {
  options: { value: T; label: string; count?: number }[];
  value: T;
  onChange: (value: T) => void;
  label: string;
}) {
  return (
    <div className="segmented" role="group" aria-label={label}>
      {options.map((o) => (
        <button key={o.value} type="button" aria-pressed={o.value === value} onClick={() => onChange(o.value)}>
          {o.label}
          {o.count !== undefined && <span className="count">{o.count}</span>}
        </button>
      ))}
    </div>
  );
}
