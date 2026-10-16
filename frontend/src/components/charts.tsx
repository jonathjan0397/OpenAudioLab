import { useState } from "react";

export function Sparkline({
  values,
  width = 90,
  height = 34,
  color = "var(--accent)",
}: {
  values: number[];
  width?: number;
  height?: number;
  color?: string;
}) {
  if (values.length < 2) return null;
  const max = Math.max(...values, 1);
  const step = width / (values.length - 1);
  const pts = values.map((v, i) => `${(i * step).toFixed(1)},${(height - 3 - (v / max) * (height - 6)).toFixed(1)}`);
  return (
    <svg className="sparkline" width={width} height={height} viewBox={`0 0 ${width} ${height}`}>
      <polyline points={pts.join(" ")} fill="none" stroke={color} strokeWidth={2} strokeLinejoin="round" />
      <polygon points={`0,${height} ${pts.join(" ")} ${width},${height}`} fill={color} opacity={0.12} />
    </svg>
  );
}

export interface Series {
  key: string;
  label: string;
  color: string;
  values: number[];
}

export function AreaChart({
  labels,
  series,
  height = 220,
}: {
  labels: string[];
  series: Series[];
  height?: number;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const width = 640;
  const pad = { l: 34, r: 8, t: 10, b: 22 };
  const n = labels.length;
  if (n < 2) return <div className="muted" style={{ color: "var(--muted)" }}>Not enough data yet.</div>;
  const totals = labels.map((_, i) => series.reduce((sum, s) => sum + (s.values[i] || 0), 0));
  const max = Math.max(...totals, 4);
  const x = (i: number) => pad.l + (i * (width - pad.l - pad.r)) / (n - 1);
  const y = (v: number) => pad.t + (1 - v / max) * (height - pad.t - pad.b);

  // stacked layers: cumulative sums
  const cum: number[][] = [];
  let acc = new Array(n).fill(0);
  for (const s of series) {
    acc = acc.map((a: number, i: number) => a + (s.values[i] || 0));
    cum.push([...acc]);
  }

  return (
    <div style={{ position: "relative" }}>
      <svg
        className="area-chart"
        viewBox={`0 0 ${width} ${height}`}
        onMouseMove={(e) => {
          const rect = (e.target as SVGElement).closest("svg")!.getBoundingClientRect();
          const px = ((e.clientX - rect.left) / rect.width) * width;
          const i = Math.round(((px - pad.l) / (width - pad.l - pad.r)) * (n - 1));
          setHover(Math.min(n - 1, Math.max(0, i)));
        }}
        onMouseLeave={() => setHover(null)}
      >
        {[0.25, 0.5, 0.75, 1].map((f) => (
          <g key={f}>
            <line x1={pad.l} x2={width - pad.r} y1={y(max * f)} y2={y(max * f)} stroke="var(--border)" strokeWidth={1} />
            <text x={pad.l - 6} y={y(max * f) + 3} textAnchor="end" fontSize={9} fill="var(--muted)">
              {Math.round(max * f)}
            </text>
          </g>
        ))}
        {series.map((s, si) => {
          const top = cum[si];
          const bottom = si === 0 ? new Array(n).fill(0) : cum[si - 1];
          const path =
            `M ${x(0)},${y(top[0])} L ` +
            top.map((v2, i) => `${x(i).toFixed(1)},${y(v2).toFixed(1)}`).join(" L ") +
            " L " +
            bottom
              .map((_b, i) => `${x(n - 1 - i).toFixed(1)},${y(bottom[n - 1 - i]).toFixed(1)}`)
              .join(" L ") +
            " Z";
          return <path key={s.key} d={path} fill={s.color} opacity={0.55} />;
        })}
        {hover !== null && (
          <line x1={x(hover)} x2={x(hover)} y1={pad.t} y2={height - pad.b} stroke="var(--muted)" strokeDasharray="3 3" />
        )}
        {labels.map((l, i) =>
          i % Math.ceil(n / 7) === 0 ? (
            <text key={l + i} x={x(i)} y={height - 6} textAnchor="middle" fontSize={9} fill="var(--muted)">
              {l.slice(5)}
            </text>
          ) : null
        )}
      </svg>
      {hover !== null && (
        <div
          className="chart-tip"
          style={{ left: `${(x(hover) / width) * 100}%`, top: `${(y(totals[hover]) / height) * 100}%` }}
        >
          {labels[hover]} · {totals[hover]} jobs
        </div>
      )}
      <div className="legend" style={{ marginTop: 8 }}>
        {series.map((s) => (
          <span key={s.key}>
            <i style={{ background: s.color }} />
            {s.label}
          </span>
        ))}
      </div>
    </div>
  );
}
