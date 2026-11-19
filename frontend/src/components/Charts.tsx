// Lightweight SVG/CSS charts. Every chart is paired with text values, so nothing is
// conveyed by colour alone.
import type { ReactNode } from "react";

export interface BarDatum {
  key: string;
  label: ReactNode;
  value: number;
  display: ReactNode;
  color?: string;
  title?: string;
}

export function BarList({ data, color = "var(--viz-estimated)", max }: { data: BarDatum[]; color?: string; max?: number }) {
  const top = max ?? Math.max(...data.map((d) => Math.abs(d.value)), 0);
  return (
    <div className="barlist">
      {data.map((d) => (
        <div className="barlist-row" key={d.key} title={d.title}>
          <div className="barlist-label">{d.label}</div>
          <div className="barlist-track" aria-hidden>
            <div className="barlist-fill" style={{ width: `${top > 0 ? (Math.abs(d.value) / top) * 100 : 0}%`, background: d.color ?? color }} />
          </div>
          <div className="barlist-value">{d.display}</div>
        </div>
      ))}
    </div>
  );
}

export interface Segment {
  key: string;
  label: string;
  value: number;
  color: string;
}

export function StackBar({ segments, label }: { segments: Segment[]; label: string }) {
  const total = segments.reduce((s, x) => s + x.value, 0);
  return (
    <div className="stackbar" role="img" aria-label={`${label}: ${segments.map((s) => `${s.label} ${s.value}`).join(", ")}`}>
      {total > 0 &&
        segments
          .filter((s) => s.value > 0)
          .map((s) => <span key={s.key} style={{ flexGrow: s.value, background: s.color }} title={`${s.label}: ${s.value}`} />)}
    </div>
  );
}

export function Legend({ items }: { items: { label: string; color: string }[] }) {
  return (
    <div className="legend">
      {items.map((i) => (
        <span key={i.label}>
          <i style={{ background: i.color }} aria-hidden />
          {i.label}
        </span>
      ))}
    </div>
  );
}

export function Donut({ segments, size = 132, thickness = 16, value, label }: { segments: Segment[]; size?: number; thickness?: number; value: ReactNode; label: string }) {
  const radius = (size - thickness) / 2;
  const circumference = 2 * Math.PI * radius;
  const total = segments.reduce((s, x) => s + x.value, 0);
  let offset = 0;
  return (
    <div className="donut" style={{ width: size, height: size }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} role="img" aria-label={`${label}: ${segments.map((s) => `${s.label} ${s.value}`).join(", ")}`}>
        <circle cx={size / 2} cy={size / 2} r={radius} fill="none" stroke="var(--viz-track)" strokeWidth={thickness} />
        {total > 0 &&
          segments
            .filter((s) => s.value > 0)
            .map((s) => {
              const length = (s.value / total) * circumference;
              const gap = segments.filter((x) => x.value > 0).length > 1 ? 2 : 0;
              const dash = `${Math.max(length - gap, 0)} ${circumference}`;
              const circle = (
                <circle
                  key={s.key}
                  cx={size / 2}
                  cy={size / 2}
                  r={radius}
                  fill="none"
                  stroke={s.color}
                  strokeWidth={thickness}
                  strokeDasharray={dash}
                  strokeDashoffset={-offset}
                  transform={`rotate(-90 ${size / 2} ${size / 2})`}
                >
                  <title>{`${s.label}: ${s.value}`}</title>
                </circle>
              );
              offset += length;
              return circle;
            })}
      </svg>
      <div className="donut-center">
        <div>
          <div className="donut-value">{value}</div>
          <div className="donut-label">{label}</div>
        </div>
      </div>
    </div>
  );
}

export interface CompareDatum {
  key: string;
  name: ReactNode;
  meta?: ReactNode;
  reported: number;
  adjusted: number;
  reportedLabel: ReactNode;
  adjustedLabel: ReactNode;
}

// As reported versus adjusted, one pair of bars per item, on a shared scale per item.
export function CompareBars({ data }: { data: CompareDatum[] }) {
  return (
    <div className="compare">
      {data.map((d) => {
        const top = Math.max(Math.abs(d.reported), Math.abs(d.adjusted), 0);
        const width = (v: number) => `${top > 0 ? (Math.abs(v) / top) * 100 : 0}%`;
        return (
          <div className="compare-row" key={d.key}>
            <div>
              <div className="compare-name">{d.name}</div>
              {d.meta && <div className="compare-meta">{d.meta}</div>}
            </div>
            <div className="compare-bars">
              <div className="compare-bar">
                <div className="barlist-track" aria-hidden>
                  <div className="barlist-fill" style={{ width: width(d.reported), background: "var(--viz-reported)" }} />
                </div>
                <div className="barlist-value">{d.reportedLabel}</div>
              </div>
              <div className="compare-bar">
                <div className="barlist-track" aria-hidden>
                  <div className="barlist-fill" style={{ width: width(d.adjusted), background: "var(--viz-adjusted)" }} />
                </div>
                <div className="barlist-value">{d.adjustedLabel}</div>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
