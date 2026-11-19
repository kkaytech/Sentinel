// Lightweight SVG/CSS charts. Every chart is paired with text values, so nothing is
// conveyed by colour alone.
import { useState, type CSSProperties, type PointerEvent, type ReactNode } from "react";

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

// SVG strokes cannot take a CSS gradient, so gradient tokens map to their solid colour.
const SOLID: Record<string, string> = {
  "var(--viz-confirmed)": "var(--c-confirmed)",
  "var(--viz-potential)": "var(--c-potential)",
  "var(--viz-estimated)": "var(--c-adjusted)",
  "var(--viz-adjusted)": "var(--c-adjusted)",
  "var(--viz-reported)": "var(--c-reported)",
};
export const solid = (color: string) => SOLID[color] ?? color;

export function Donut({
  segments,
  size = 132,
  thickness = 16,
  value,
  label,
  active,
  onActive,
}: {
  segments: Segment[];
  size?: number;
  thickness?: number;
  value: ReactNode;
  label: string;
  active?: string | null;
  onActive?: (key: string | null) => void;
}) {
  const [own, setOwn] = useState<string | null>(null);
  const current = active !== undefined ? active : own;
  const setCurrent = onActive ?? setOwn;
  const shown = segments.find((s) => s.key === current && s.value > 0);
  const radius = (size - thickness) / 2;
  const circumference = 2 * Math.PI * radius;
  const total = segments.reduce((s, x) => s + x.value, 0);
  let offset = 0;
  return (
    <div className={`donut ${shown ? "hovering" : ""}`} style={{ width: size, height: size }} onMouseLeave={() => setCurrent(null)}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} role="img" aria-label={`${label}: ${segments.map((s) => `${s.label} ${s.value}`).join(", ")}`}>
        <circle cx={size / 2} cy={size / 2} r={radius} fill="none" stroke="rgba(148, 163, 196, 0.1)" strokeWidth={thickness} />
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
                  className={`seg ${s.key === current ? "on" : ""}`}
                  onMouseEnter={() => setCurrent(s.key)}
                  cx={size / 2}
                  cy={size / 2}
                  r={radius}
                  fill="none"
                  stroke={solid(s.color)}
                  strokeLinecap="butt"
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
          <div className="donut-value">{shown ? shown.value.toLocaleString("en-GB") : value}</div>
          <div className="donut-label">{shown ? shown.label : label}</div>
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

export interface SeriesValue {
  label: string;
  value: number;
  color: string;
  display: ReactNode;
}

// Several bars per row on one shared scale, so rows (for example periods) compare directly.
export function SeriesBars({ rows }: { rows: { key: string; label: ReactNode; values: SeriesValue[] }[] }) {
  const top = Math.max(0, ...rows.flatMap((r) => r.values.map((v) => Math.abs(v.value))));
  return (
    <div className="series">
      {rows.map((r) => (
        <div className="series-row" key={r.key}>
          <div className="series-label">{r.label}</div>
          <div className="series-bars">
            {r.values.map((v) => (
              <div className="series-bar" key={v.label} title={v.label}>
                <div className="barlist-track" aria-hidden>
                  <div className="barlist-fill" style={{ width: `${top > 0 ? (Math.abs(v.value) / top) * 100 : 0}%`, background: v.color }} />
                </div>
                <div className="barlist-value">
                  <span className="sr-only">{v.label}: </span>
                  {v.display}
                </div>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

// One stacked bar per row, scaled to the largest row total.
export function StackRows({ rows }: { rows: { key: string; label: ReactNode; segments: Segment[]; total: ReactNode }[] }) {
  const top = Math.max(0, ...rows.map((r) => r.segments.reduce((s, x) => s + x.value, 0)));
  return (
    <div className="stack-rows">
      {rows.map((r) => {
        const sum = r.segments.reduce((s, x) => s + x.value, 0);
        return (
          <div className="stack-row" key={r.key}>
            <div className="series-label">{r.label}</div>
            <div style={{ width: `${top > 0 ? Math.max((sum / top) * 100, sum > 0 ? 2 : 0) : 0}%`, minWidth: sum > 0 ? 8 : 0 }}>
              {sum > 0 ? <StackBar segments={r.segments} label={String(r.key)} /> : <div className="stackbar" />}
            </div>
            <div className="barlist-value">{r.total}</div>
          </div>
        );
      })}
    </div>
  );
}

// ---- Sparkline ---------------------------------------------------------------------------------
// Hovering reads the value of the nearest period. The path morphs when the figures change.
export function Sparkline({
  values,
  color = "#5b82ff",
  highlight,
  label,
  labels,
  format = (v) => v.toLocaleString("en-GB"),
}: {
  values: number[];
  color?: string;
  highlight?: number;
  label: string;
  labels?: string[];
  format?: (v: number) => string;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const id = `spark-${label.replace(/[^a-z0-9]/gi, "")}`;
  if (values.length < 2) {
    return <svg viewBox="0 0 100 40" preserveAspectRatio="none" role="img" aria-label={`${label}: not enough periods for a trend`} />;
  }
  const max = Math.max(...values, 0);
  const min = Math.min(...values, 0);
  const span = max - min || 1;
  const pts = values.map((v, i) => [(i / (values.length - 1)) * 100, 36 - ((v - min) / span) * 30] as const);
  // Smooth curve: horizontal-tangent cubic segments between points.
  const line = pts
    .map(([x, y], i) => {
      if (i === 0) return `M${x.toFixed(2)},${y.toFixed(2)}`;
      const [px, py] = pts[i - 1];
      const cx = (px + x) / 2;
      return `C${cx.toFixed(2)},${py.toFixed(2)} ${cx.toFixed(2)},${y.toFixed(2)} ${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .join(" ");
  const area = `${line} L100,40 L0,40 Z`;
  const morph = (d: string) => ({ d: `path("${d}")` }) as CSSProperties;
  const point = hover ?? highlight;
  const onMove = (event: PointerEvent<HTMLDivElement>) => {
    const r = event.currentTarget.getBoundingClientRect();
    setHover(Math.min(values.length - 1, Math.max(0, Math.round(((event.clientX - r.left) / r.width) * (values.length - 1)))));
  };
  return (
    <div style={{ position: "relative", height: "100%" }} onPointerMove={onMove} onPointerLeave={() => setHover(null)}>
      {hover !== null && (
        <div className="spark-tip" style={{ left: `${pts[hover][0]}%` }} aria-hidden>
          {labels?.[hover] && <span>{labels[hover]}</span>}
          {format(values[hover])}
        </div>
      )}
      <svg viewBox="0 0 100 40" preserveAspectRatio="none" role="img" aria-label={`${label} by period: ${values.map((v, i) => (labels ? `${labels[i]} ${format(v)}` : format(v))).join(", ")}`}>
        <defs>
          <linearGradient id={id} x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity="0.38" />
            <stop offset="100%" stopColor={color} stopOpacity="0" />
          </linearGradient>
        </defs>
        <path d={area} style={morph(area)} fill={`url(#${id})`} className="funnel-path spark-path" />
        <path d={line} style={morph(line)} fill="none" stroke={color} strokeWidth="1.8" vectorEffect="non-scaling-stroke" strokeLinejoin="round" className="funnel-path spark-path" />
        {hover !== null && <line x1={pts[hover][0]} x2={pts[hover][0]} y1={0} y2={40} style={{ stroke: "var(--border-strong)" }} strokeWidth="1" vectorEffect="non-scaling-stroke" strokeDasharray="2 2" />}
        {point !== undefined && point !== null && pts[point] && (
          <circle className="spark-dot" cx={pts[point][0]} cy={pts[point][1]} style={{ cx: pts[point][0], cy: pts[point][1] } as CSSProperties} r="2.6" fill="#fff" stroke={color} strokeWidth="1.5" vectorEffect="non-scaling-stroke" />
        )}
      </svg>
    </div>
  );
}

// ---- Interactive column chart -------------------------------------------------------------------
export interface ColumnDatum {
  key: string;
  label: string;
  values: { label: string; value: number; color: string; display: string; detail?: string }[];
  note?: string;
}

export function ColumnChart({ data, selected, onSelect, ticks }: { data: ColumnDatum[]; selected?: string | null; onSelect?: (key: string) => void; ticks?: (fraction: number) => string }) {
  const [hover, setHover] = useState<string | null>(null);
  const top = Math.max(0, ...data.flatMap((d) => d.values.map((v) => Math.abs(v.value))));
  return (
    <div className="columns">
      <div className="columns-grid" aria-hidden>
        {[1, 0.75, 0.5, 0.25, 0].map((f) => (
          <span key={f}>{ticks && top > 0 ? ticks(top * f) : ""}</span>
        ))}
      </div>
      {data.map((d) => (
        <button
          key={d.key}
          type="button"
          className={`col ${selected === d.key ? "selected" : selected ? "dim" : ""}`}
          aria-pressed={selected === d.key}
          aria-label={`${d.label}: ${d.values.map((v) => `${v.label} ${v.display}${v.detail ? `, ${v.detail}` : ""}`).join("; ")}`}
          onClick={() => onSelect?.(d.key)}
          onMouseEnter={() => setHover(d.key)}
          onMouseLeave={() => setHover(null)}
          onFocus={() => setHover(d.key)}
          onBlur={() => setHover(null)}
        >
          {hover === d.key && (
            <div className="tooltip" role="tooltip">
              <div className="tooltip-title">{d.label}</div>
              {d.values.map((v) => (
                <div className="tooltip-row" key={v.label}>
                  <i style={{ background: v.color }} />
                  {v.label}
                  <strong>
                    {v.display}
                    {v.detail && <em>{v.detail}</em>}
                  </strong>
                </div>
              ))}
              {d.note && <div className="tooltip-sub">{d.note}</div>}
            </div>
          )}
          <div className="col-bars">
            {d.values.map((v, n) => (
              <div
                key={v.label}
                className="col-bar"
                data-zero={v.value === 0}
                style={{ height: `${top > 0 ? Math.max((Math.abs(v.value) / top) * 100, v.value ? 1.5 : 0) : 0}%`, background: v.color, animationDelay: `${n * 80}ms` }}
              />
            ))}
          </div>
          <div className="col-label">{d.label}</div>
        </button>
      ))}
    </div>
  );
}

// ---- Pipeline funnel ----------------------------------------------------------------------------
// An extruded ribbon on a tilted stage. Hovering a stage names the periods that reached it.
export function Funnel({ stages, highlight }: { stages: { label: string; count: number; periods?: string[] }[]; highlight?: number | null }) {
  const [hover, setHover] = useState<number | null>(null);
  const total = Math.max(stages[0]?.count ?? 0, 1);
  const w = 1000;
  const h = 200;
  const depth = 18;
  const mid = h / 2;
  const xs = stages.map((_, i) => (i / Math.max(stages.length - 1, 1)) * w);
  const half = stages.map((s) => Math.max((s.count / total) * (h / 2 - 8), 4));
  // Top edge left to right, then the bottom edge right to left, with smooth S-curves.
  let path = `M0,${mid - half[0]}`;
  for (let i = 1; i < xs.length; i++) {
    const cx = (xs[i - 1] + xs[i]) / 2;
    path += ` C${cx},${mid - half[i - 1]} ${cx},${mid - half[i]} ${xs[i]},${mid - half[i]}`;
  }
  path += ` L${xs[xs.length - 1]},${mid + half[xs.length - 1]}`;
  for (let i = xs.length - 2; i >= 0; i--) {
    const cx = (xs[i + 1] + xs[i]) / 2;
    path += ` C${cx},${mid + half[i + 1]} ${cx},${mid + half[i]} ${xs[i]},${mid + half[i]}`;
  }
  path += " Z";
  const edges = xs.map((x, i) => [i === 0 ? 0 : (xs[i - 1] + x) / 2, i === xs.length - 1 ? w : (x + xs[i + 1]) / 2]);
  const active = hover ?? highlight ?? null;
  const info = active !== null ? stages[active] : null;
  return (
    <div className="funnel" onMouseLeave={() => setHover(null)}>
      <div className="funnel-stages">
        {stages.map((s, i) => (
          <div className={`funnel-stage ${highlight === i ? "here" : ""} ${hover === i ? "hot" : ""}`} key={s.label} onMouseEnter={() => setHover(i)}>
            <div className="l">
              {i + 1}. {s.label}
            </div>
            <div className="n">{s.count}</div>
            <span className="p">{Math.round((s.count / total) * 100)}%</span>
          </div>
        ))}
      </div>
      <div className="funnel-3d">
        <svg viewBox={`0 0 ${w} ${h + depth + 50}`} role="img" aria-label={`Publication pipeline: ${stages.map((s) => `${s.label} ${s.count}`).join(", ")}`}>
          <defs>
            <linearGradient id="funnel-fill" x1="0" x2="1" y1="0" y2="0">
              <stop offset="0%" stopColor="#2dd4bf" stopOpacity="0.95" />
              <stop offset="35%" stopColor="#22b8e8" stopOpacity="0.92" />
              <stop offset="70%" stopColor="#3b6cf6" stopOpacity="0.9" />
              <stop offset="100%" stopColor="#4338ca" stopOpacity="0.9" />
            </linearGradient>
            <linearGradient id="funnel-side" x1="0" x2="1" y1="0" y2="0">
              <stop offset="0%" stopColor="#0f5f66" />
              <stop offset="50%" stopColor="#173f8f" />
              <stop offset="100%" stopColor="#1e1b6b" />
            </linearGradient>
            <linearGradient id="funnel-shine" x1="0" x2="0" y1="0" y2="1">
              <stop offset="0%" stopColor="#fff" stopOpacity="0.32" />
              <stop offset="45%" stopColor="#fff" stopOpacity="0" />
            </linearGradient>
            <linearGradient id="funnel-fade" x1="0" x2="0" y1="0" y2="1">
              <stop offset="0%" stopColor="#fff" stopOpacity="0.22" />
              <stop offset="60%" stopColor="#fff" stopOpacity="0" />
            </linearGradient>
            <mask id="funnel-reflect-mask">
              <rect x="0" y={h + depth} width={w} height="50" fill="url(#funnel-fade)" />
            </mask>
            <clipPath id="funnel-clip">
              <path d={path} />
            </clipPath>
            <filter id="funnel-glow" x="-10%" y="-40%" width="120%" height="180%">
              <feGaussianBlur stdDeviation="14" />
            </filter>
          </defs>
          {/* Floor reflection, then the extruded side, then the lit top face. */}
          <g mask="url(#funnel-reflect-mask)" className="funnel-path">
            <path d={path} fill="url(#funnel-fill)" transform={`translate(0 ${2 * h + depth + 6}) scale(1 -1)`} />
          </g>
          <path d={path} fill="url(#funnel-fill)" opacity="0.35" filter="url(#funnel-glow)" className="funnel-path" />
          <path d={path} fill="url(#funnel-side)" transform={`translate(0 ${depth})`} className="funnel-path" />
          <path d={path} fill="url(#funnel-fill)" className="funnel-path" />
          <path d={path} fill="url(#funnel-shine)" className="funnel-path" />
          {active !== null && (
            <rect x={edges[active][0]} y={0} width={edges[active][1] - edges[active][0]} height={h} fill="#fff" opacity="0.14" clipPath="url(#funnel-clip)" style={{ transition: "x 300ms, width 300ms" }} />
          )}
          {xs.map((x, i) => (
            <line key={i} x1={x} x2={x} y1={4} y2={h - 4} stroke={highlight === i ? "#99f6e4" : "rgba(255,255,255,0.2)"} strokeWidth={highlight === i ? 2 : 1} strokeDasharray={highlight === i ? "" : "3 5"} />
          ))}
          {edges.map(([a, b], i) => (
            <rect key={i} className="funnel-seg" x={a} y={0} width={b - a} height={h + depth} fill="transparent" onMouseEnter={() => setHover(i)} />
          ))}
        </svg>
      </div>
      <div className="funnel-tip" aria-live="polite">
        {info ? (
          <>
            <strong>{info.label}</strong>: {info.count} of {stages[0]?.count ?? 0} {stages[0]?.count === 1 ? "period" : "periods"} ({Math.round((info.count / total) * 100)}%)
            {info.periods && info.periods.length > 0 && <> · {info.periods.join(", ")}</>}
          </>
        ) : (
          "Hover a stage to see which periods have reached it."
        )}
      </div>
    </div>
  );
}

// ---- Gauge --------------------------------------------------------------------------------------
export function Gauge({ value, max, label, display, size = 190, tone = "cool" }: { value: number; max: number; label: string; display: ReactNode; size?: number; tone?: "cool" | "danger" | "ok" }) {
  const stroke = 14;
  const r = (size - stroke) / 2;
  const circumference = 2 * Math.PI * r;
  const arc = circumference * 0.75; // a 270-degree gauge
  const fraction = max > 0 ? Math.min(Math.max(value / max, 0), 1) : 0;
  const stops = tone === "danger" ? ["#f43f5e", "#fb923c"] : tone === "ok" ? ["#10b981", "#2dd4bf"] : ["#2dd4bf", "#3b6cf6"];
  const id = `gauge-${tone}`;
  return (
    <div className="gauge" style={{ width: size, height: size }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} role="img" aria-label={`${label}: ${Math.round(fraction * 100)}%`}>
        <defs>
          <linearGradient id={id} x1="0" x2="1" y1="1" y2="0">
            <stop offset="0%" stopColor={stops[0]} />
            <stop offset="100%" stopColor={stops[1]} />
          </linearGradient>
          <radialGradient id="gauge-lens" cx="40%" cy="30%" r="75%">
            <stop offset="0%" stopColor="#7dd3fc" stopOpacity="0.16" />
            <stop offset="60%" stopColor="#3b6cf6" stopOpacity="0.05" />
            <stop offset="100%" stopColor="#0b1530" stopOpacity="0" />
          </radialGradient>
          <filter id={`${id}-glow`} x="-30%" y="-30%" width="160%" height="160%">
            <feGaussianBlur stdDeviation="6" />
          </filter>
        </defs>
        {/* A glass lens behind the figure gives the dial depth. */}
        <circle cx={size / 2} cy={size / 2} r={r - stroke} fill="url(#gauge-lens)" stroke="rgba(148,190,230,0.12)" />
        <g transform={`rotate(135 ${size / 2} ${size / 2})`}>
          <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="rgba(148,163,196,0.12)" strokeWidth={stroke} strokeDasharray={`${arc} ${circumference}`} strokeLinecap="round" />
          <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={`url(#${id})`} strokeWidth={stroke} strokeDasharray={`${arc} ${circumference}`} strokeDashoffset={arc * (1 - fraction)} strokeLinecap="round" className="gauge-arc" filter={`url(#${id}-glow)`} opacity="0.55" />
          <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={`url(#${id})`} strokeWidth={stroke} strokeDasharray={`${arc} ${circumference}`} strokeDashoffset={arc * (1 - fraction)} strokeLinecap="round" className="gauge-arc" />
        </g>
      </svg>
      <div className="gauge-center">
        <div>
          <div className="gauge-value">{display}</div>
          <div className="gauge-label">{label}</div>
        </div>
      </div>
    </div>
  );
}
