import { ReactNode } from "react";

export function Segmented<T extends string>({
  options,
  value,
  onChange,
}: {
  options: { value: T; label: ReactNode }[];
  value: T;
  onChange: (v: T) => void;
}) {
  return (
    <div className="segmented" role="tablist">
      {options.map((o) => (
        <button key={o.value} type="button" className={o.value === value ? "active" : ""} onClick={() => onChange(o.value)}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function Chip({
  active,
  onClick,
  children,
}: {
  active?: boolean;
  onClick?: () => void;
  children: ReactNode;
}) {
  return (
    <button type="button" className={`chip${active ? " active" : ""}`} onClick={onClick}>
      {children}
    </button>
  );
}

export function Tabs({
  tabs,
  value,
  onChange,
}: {
  tabs: { value: string; label: string }[];
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <div className="tabs">
      {tabs.map((t) => (
        <button key={t.value} type="button" className={t.value === value ? "active" : ""} onClick={() => onChange(t.value)}>
          {t.label}
        </button>
      ))}
    </div>
  );
}

const PILL_CLASS: Record<string, string> = {
  succeeded: "ok",
  completed: "ok",
  online: "ok",
  healthy: "ok",
  running: "info",
  processing: "info",
  busy: "info",
  training: "info",
  queued: "muted",
  waiting_for_worker: "muted",
  pending: "muted",
  failed: "err",
  cancelled: "warn",
  draining: "warn",
};

export function StatusPill({ status, label }: { status: string; label?: string }) {
  const cls = PILL_CLASS[status] || "muted";
  return <span className={`pill ${cls}`}>{label || status.replace(/_/g, " ")}</span>;
}

export function Progress({ value, width }: { value: number; width?: number | string }) {
  return (
    <div className="progress" style={{ width }}>
      <i style={{ width: `${Math.round(Math.min(1, Math.max(0, value)) * 100)}%` }} />
    </div>
  );
}

export function Donut({ value, size = 64, label }: { value: number; size?: number; label?: string }) {
  const r = (size - 8) / 2;
  const c = 2 * Math.PI * r;
  const v = Math.min(1, Math.max(0, value));
  return (
    <svg className="donut" width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--border)" strokeWidth={6} />
      <circle
        cx={size / 2}
        cy={size / 2}
        r={r}
        fill="none"
        stroke="var(--accent)"
        strokeWidth={6}
        strokeLinecap="round"
        strokeDasharray={`${c * v} ${c}`}
        transform={`rotate(-90 ${size / 2} ${size / 2})`}
      />
      {label && (
        <text x="50%" y="54%" textAnchor="middle" dominantBaseline="middle" fontSize={size / 5} fontWeight={700} fill="var(--text)">
          {label}
        </text>
      )}
    </svg>
  );
}

export function Skeleton({ h = 16, w = "100%" }: { h?: number; w?: number | string }) {
  return <div className="skeleton" style={{ height: h, width: w }} />;
}

export function Delta({ value, vs }: { value: number; vs?: string }) {
  const up = value >= 0;
  return (
    <span className={`delta ${up ? "up" : "down"}`}>
      {up ? "↑" : "↓"} {up ? "+" : ""}
      {value}%{vs ? ` ${vs}` : ""}
    </span>
  );
}

export function Avatar({ name, sm }: { name: string; sm?: boolean }) {
  const initials = name
    .split(/[\s._-]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0].toUpperCase())
    .join("");
  return (
    <span className={`avatar${sm ? " sm" : ""}`} title={name}>
      {initials || "?"}
    </span>
  );
}

export function fmtTime(seconds: number | null | undefined): string {
  if (!seconds && seconds !== 0) return "0:00";
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}
