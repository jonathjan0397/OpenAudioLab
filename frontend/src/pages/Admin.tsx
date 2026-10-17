import { useState } from "react";
import { NavLink, useLocation } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, AuthUser, SiteInfo } from "../api";
import { AreaChart, Sparkline } from "../components/charts";
import { Avatar, Delta, Progress, StatusPill } from "../components/ui";

interface AdminUser {
  id: string;
  email: string;
  username: string;
  role: string;
  state: string;
  credits_balance: number;
}
interface Stats {
  users_total: number;
  active_users_30d: number;
  active_users_prev_30d: number;
  jobs_today: number;
  jobs_yesterday: number;
  jobs_active: number;
  assets_total: number;
  storage_bytes: number;
  gpu_util_avg: number | null;
  revenue: number;
  credits_used: number;
  credits_quota: number;
  workers: {
    id: string;
    kind: string;
    drain: boolean;
    gpu_util: number | null;
    vram_used_mb: number | null;
    vram_total_mb: number | null;
    last_heartbeat: string | null;
  }[];
}
interface DayPoint {
  date: string;
  completed: number;
  failed: number;
  cancelled: number;
  active: number;
  new_users: number;
}
interface Service {
  name: string;
  kind: string;
  operation: string;
  version: string;
  status: string;
  requests_24h: number;
  avg_latency_seconds: number | null;
  success_rate: number | null;
  uptime_pct: number;
}
interface Training {
  run_id: string;
  profile: string;
  user: string;
  status: string;
  stage: string | null;
  progress: number | null;
  eta_seconds: number | null;
  created_at: string | null;
  hardware: string | null;
}
interface AdminJob {
  job_id: string;
  owner_id: string;
  user: string;
  operation: string;
  task: string;
  status: string;
  stage?: string | null;
  progress?: number | null;
  error_code?: string | null;
  runtime_seconds?: number | null;
  created_at: string | null;
  started_at: string | null;
  finished_at: string | null;
}
interface StorageInfo {
  total_bytes: number;
  quota_bytes: number;
  categories: { generated_audio: number; training_data: number; model_checkpoints: number; other: number };
}
interface Billing {
  revenue: number;
  revenue_delta_pct: number;
  credits_used: number;
  credits_granted: number;
  credits_quota: number;
  credits_pct: number;
  subscriptions_pct: number;
  api_usage_pct: number;
  custom_training_pct: number;
}
interface AuditRow {
  event: string;
  status: string;
  stage: string | null;
  job_id: string;
  owner_id: string;
  operation: string;
  created_at: string | null;
}
interface WorkerRow {
  id: string;
  kind: string;
  drain: boolean;
  status: string;
  gpu_util: number | null;
  vram_used_mb: number | null;
  vram_total_mb: number | null;
  last_heartbeat: string | null;
}

const SIDEBAR = [
  { to: "/admin", label: "Overview", icon: "⌂" },
  { to: "/admin/users", label: "Users", icon: "☺" },
  { to: "/admin/jobs", label: "Generation Jobs", icon: "⇍" },
  { to: "/admin/services", label: "Model Services", icon: "▣" },
  { to: "/admin/workers", label: "GPU Workers", icon: "▦" },
  { to: "/admin/training", label: "Artist Training", icon: "◈" },
  { to: "/admin/storage", label: "Storage", icon: "▤" },
  { to: "/admin/billing", label: "Billing", icon: "▥" },
  { to: "/admin/api", label: "API Access", icon: "</>" },
  { to: "/admin/audit", label: "Audit Log", icon: "▦" },
  { to: "/admin/settings", label: "Settings", icon: "⚙" },
];

const TEMPLATES = ["open-canvas", "analog-soul", "neon-studio", "signal-lab"];

function fmtRuntime(secs: number | null | undefined): string {
  if (secs == null) return "—";
  return secs >= 60 ? `${Math.floor(secs / 60)}m ${Math.round(secs % 60)}s` : `${Math.round(secs)}s`;
}

function fmtEta(secs: number | null): string {
  if (secs == null) return "—";
  return secs >= 3600 ? `${Math.floor(secs / 3600)}h ${Math.round((secs % 3600) / 60)}m` : secs >= 60 ? `${Math.round(secs / 60)}m` : `${secs}s`;
}

function fmtTb(bytes: number): string {
  return bytes >= 1e12 ? `${(bytes / 1e12).toFixed(2)} TB` : bytes >= 1e9 ? `${(bytes / 1e9).toFixed(1)} GB` : `${(bytes / 1e6).toFixed(1)} MB`;
}

function pctDelta(now: number, prev: number): number | null {
  if (!prev) return null;
  return Math.round(((now - prev) / prev) * 100);
}

export default function AdminPage() {
  const qc = useQueryClient();
  const location = useLocation();
  const section = location.pathname.replace(/^\/admin\/?/, "") || "overview";

  const [days, setDays] = useState(14);
  const [granularity, setGranularity] = useState<"day" | "hour">("day");
  const [task, setTask] = useState("all");
  const [metric, setMetric] = useState<"tracks" | "users" | "compute">("tracks");
  const [userQ, setUserQ] = useState("");
  const [jobStatus, setJobStatus] = useState("");

  const me = useQuery({
    queryKey: ["me"],
    queryFn: () => api.get<{ user: AuthUser }>("/api/v1/auth/me"),
    retry: false,
  });
  const isAdmin = me.data?.user?.role === "admin";
  const enabled = !!isAdmin;
  const stats = useQuery({
    queryKey: ["admin-stats"],
    queryFn: () => api.get<Stats>("/api/v1/admin/stats"),
    enabled,
    refetchInterval: 15000,
  });
  const series = useQuery({
    queryKey: ["admin-timeseries", days, granularity, task],
    queryFn: () =>
      api.get<{ series: DayPoint[] }>(
        `/api/v1/admin/stats/timeseries?days=${days}&granularity=${granularity}&task=${task}`
      ),
    enabled,
    refetchInterval: 60000,
  });
  const recent = useQuery({
    queryKey: ["admin-jobs", "recent"],
    queryFn: () => api.get<AdminJob[]>("/api/v1/admin/jobs?limit=8"),
    enabled,
    refetchInterval: 10000,
  });
  const allJobs = useQuery({
    queryKey: ["admin-jobs", "all", jobStatus],
    queryFn: () => api.get<AdminJob[]>(`/api/v1/admin/jobs?limit=100${jobStatus ? `&status=${jobStatus}` : ""}`),
    enabled: enabled && section === "jobs",
    refetchInterval: 10000,
  });
  const services = useQuery({
    queryKey: ["admin-services"],
    queryFn: () => api.get<{ services: Service[] }>("/api/v1/admin/services"),
    enabled,
    refetchInterval: 30000,
  });
  const workers = useQuery({
    queryKey: ["admin-workers"],
    queryFn: () => api.get<{ workers: WorkerRow[] }>("/api/v1/admin/workers"),
    enabled,
    refetchInterval: 15000,
  });
  const trainings = useQuery({
    queryKey: ["admin-trainings"],
    queryFn: () => api.get<Training[]>("/api/v1/admin/trainings?limit=8"),
    enabled,
    refetchInterval: 10000,
  });
  const storage = useQuery({
    queryKey: ["admin-storage"],
    queryFn: () => api.get<StorageInfo>("/api/v1/admin/storage"),
    enabled,
    refetchInterval: 60000,
  });
  const billing = useQuery({
    queryKey: ["admin-billing"],
    queryFn: () => api.get<Billing>("/api/v1/admin/billing"),
    enabled,
    refetchInterval: 60000,
  });
  const audit = useQuery({
    queryKey: ["admin-audit"],
    queryFn: () => api.get<AuditRow[]>("/api/v1/admin/audit?limit=50"),
    enabled: enabled && section === "audit",
  });
  const users = useQuery({
    queryKey: ["admin-users", userQ],
    queryFn: () => api.get<{ users: AdminUser[]; total: number }>(`/api/v1/admin/users${userQ ? `?q=${encodeURIComponent(userQ)}` : ""}`),
    enabled,
  });
  const site = useQuery({ queryKey: ["site"], queryFn: () => api.get<SiteInfo>("/api/v1/site") });

  const [email, setEmail] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["admin-users"] });
    qc.invalidateQueries({ queryKey: ["admin-stats"] });
  };
  const create = useMutation({
    mutationFn: () => api.post<{ user: AdminUser }>("/api/v1/admin/users", { email, username, password }),
    onSuccess: () => {
      setError("");
      setEmail("");
      setUsername("");
      setPassword("");
      invalidate();
    },
    onError: (e: Error) => setError(e.message),
  });
  const patch = useMutation({
    mutationFn: ({ id, body }: { id: string; body: Record<string, string> }) =>
      api.patch(`/api/v1/admin/users/${id}`, body),
    onSuccess: invalidate,
  });
  const setTemplate = useMutation({
    mutationFn: (value: string) => api.put("/api/v1/admin/settings/template", { value }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["site"] }),
  });

  if (!me.data?.user) return <main className="page"><h1>Admin</h1><p>Sign in first.</p></main>;
  if (!isAdmin) return <main className="page"><h1>Admin</h1><p>Admin role required.</p></main>;

  const daysData = series.data?.series || [];
  const labels = daysData.map((d) => d.date.slice(5).replace("T", "h"));
  const metricValues =
    metric === "tracks" ? daysData.map((d) => d.completed)
    : metric === "users" ? daysData.map((d) => d.new_users)
    : daysData.map((d) => d.active);
  const completed = daysData.map((d) => d.completed);
  const newUsers = daysData.map((d) => d.new_users);

  const s = stats.data;
  const usersDelta = s ? pctDelta(s.active_users_30d, s.active_users_prev_30d) : null;
  const jobsDelta = s ? pctDelta(s.jobs_today, s.jobs_yesterday) : null;

  const jobTable = (rows: AdminJob[]) => (
    <table className="table">
      <thead>
        <tr><th>Job ID</th><th>User</th><th>Task</th><th>Status</th><th>Runtime</th><th>Created</th></tr>
      </thead>
      <tbody>
        {rows.map((j) => (
          <tr key={j.job_id}>
            <td className="mono">{j.job_id.slice(0, 8)}</td>
            <td><Avatar name={j.user} sm /> {j.user}</td>
            <td>{j.task}</td>
            <td><StatusPill status={j.status} /></td>
            <td>{fmtRuntime(j.runtime_seconds)}</td>
            <td className="mono">{j.created_at?.slice(5, 16).replace("T", " ")}</td>
          </tr>
        ))}
        {rows.length === 0 && <tr><td colSpan={6} style={{ color: "var(--muted)" }}>No jobs yet.</td></tr>}
      </tbody>
    </table>
  );

  const serviceRow = (sv: Service) => (
    <div key={sv.name} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "7px 0", fontSize: 13, gap: 12 }}>
      <div style={{ minWidth: 0 }}>
        <strong>{sv.name}</strong>
        <div className="mono">{sv.kind} · {sv.version}</div>
      </div>
      <span className="mono" style={{ color: "var(--muted)", fontSize: 12 }}>
        {sv.requests_24h} req/24h{sv.avg_latency_seconds != null ? ` · ${sv.avg_latency_seconds}s` : ""}{sv.success_rate != null ? ` · ${sv.success_rate}%` : ""}
      </span>
      <StatusPill status={sv.status} />
    </div>
  );

  const workerRow = (w: WorkerRow) => {
    const vramPct = w.vram_used_mb && w.vram_total_mb ? w.vram_used_mb / w.vram_total_mb : 0;
    return (
      <div key={w.id} style={{ marginBottom: 14 }}>
        <div style={{ display: "flex", justifyContent: "space-between", gap: 8, fontSize: 13, marginBottom: 4 }}>
          <strong>{w.id}</strong>
          <StatusPill status={w.status === "stale" ? "failed" : w.status === "draining" ? "cancelled" : "online"} label={w.status} />
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 12, color: "var(--muted)" }}>
          <span style={{ width: 38 }}>{w.gpu_util != null ? `${w.gpu_util}%` : "—"}</span>
          <div style={{ flex: 1 }}>
            <Progress value={vramPct} />
          </div>
          <span className="mono">
            {w.vram_used_mb != null && w.vram_total_mb != null
              ? `${(w.vram_used_mb / 1024).toFixed(1)}/${(w.vram_total_mb / 1024).toFixed(0)} GB`
              : "no vram data"}
          </span>
        </div>
      </div>
    );
  };

  const trainingRow = (t: Training) => (
    <div key={t.run_id} style={{ marginBottom: 12 }}>
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13, marginBottom: 4 }}>
        <strong>{t.profile}</strong>
        <StatusPill status={t.status} />
      </div>
      <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 4 }}>
        {t.user} · {t.stage ? `${t.stage}…` : t.status === "succeeded" ? "done" : "queued…"}
        {t.progress != null ? ` · ${Math.round(t.progress * 100)}%` : ""}
        {t.eta_seconds != null ? ` · ETA ${fmtEta(t.eta_seconds)}` : ""}
      </div>
      <Progress value={t.progress ?? (t.status === "succeeded" ? 1 : 0)} />
    </div>
  );

  return (
    <div className="dash">
      <aside className="dash-sidebar">
        {SIDEBAR.map((item) => (
          <NavLink key={item.to} to={item.to} end={item.to === "/admin"} className={({ isActive }) => (isActive ? "active" : "")}>
            <span aria-hidden>{item.icon}</span> {item.label}
          </NavLink>
        ))}
        <div className="side-note">OpenAudioLab — platform operations.</div>
      </aside>
      <div className="dash-main">
        <div className="hero-strip admin-strip">
          <div>
            <h1>Admin {section === "overview" ? "Overview" : SIDEBAR.find((x) => x.to.endsWith("/" + section))?.label}</h1>
            <div className="sub">Monitor platform health, usage, and operations in real time.</div>
          </div>
          <div className="strip-controls">
            <select disabled title="Environment switching coming soon"><option>● Production</option></select>
            <select disabled title="Date ranges coming soon"><option>Last 14 days</option></select>
          </div>
        </div>

        {section === "overview" && (
          <>
            <div className="stat-grid">
              <div className="card stat-card">
                <span className="icon">☺</span>
                <div>
                  <div className="label">Active Users</div>
                  <div className="value">{s?.active_users_30d ?? "-"}</div>
                  {usersDelta != null && <Delta value={usersDelta} vs="vs. prior 30d" />}
                </div>
                <span className="chart"><Sparkline values={newUsers.length ? newUsers : [0, 0]} /></span>
              </div>
              <div className="card stat-card">
                <span className="icon">⇍</span>
                <div>
                  <div className="label">Jobs Today</div>
                  <div className="value">{s?.jobs_today ?? "-"}</div>
                  {jobsDelta != null && <Delta value={jobsDelta} vs="vs. yesterday" />}
                </div>
                <span className="chart"><Sparkline values={completed.length ? completed : [0, 0]} /></span>
              </div>
              <div className="card stat-card">
                <span className="icon">▦</span>
                <div>
                  <div className="label">GPU Utilization</div>
                  <div className="value">{s?.gpu_util_avg != null ? `${s.gpu_util_avg}%` : "—"}</div>
                  <div className="sub">{s?.jobs_active ?? 0} active jobs</div>
                </div>
              </div>
              <div className="card stat-card">
                <span className="icon">▥</span>
                <div>
                  <div className="label">Revenue</div>
                  <div className="value">${(s?.revenue ?? 0).toLocaleString()}</div>
                  <div className="sub">vs. last month</div>
                </div>
              </div>
            </div>

            <div className="card" style={{ marginTop: 20 }}>
              <div className="card-header">
                <h2>Generation Activity</h2>
                <span className="spacer" />
                <div className="segmented">
                  {(["tracks", "users", "compute"] as const).map((m) => (
                    <button key={m} type="button" className={m === metric ? "active" : ""} onClick={() => setMetric(m)}>{m}</button>
                  ))}
                </div>
                <select style={{ width: 110 }} value={task} onChange={(e) => setTask(e.target.value)}>
                  <option value="all">All Tasks</option>
                  <option value="generate">Text to Music</option>
                  <option value="export">Audio Export</option>
                  <option value="training">Artist Training</option>
                </select>
                <div className="segmented">
                  <button type="button" className={granularity === "day" ? "active" : ""} onClick={() => setGranularity("day")}>Daily</button>
                  <button type="button" className={granularity === "hour" ? "active" : ""} onClick={() => setGranularity("hour")}>Hourly</button>
                </div>
                <select style={{ width: 110 }} value={days} onChange={(e) => setDays(Number(e.target.value))}>
                  {[7, 14, 30].map((d) => <option key={d} value={d}>Last {d} days</option>)}
                </select>
              </div>
              <AreaChart
                labels={labels}
                series={[
                  { key: "metric", label: metric === "tracks" ? "Completed" : metric === "users" ? "New Users" : "Active", color: "var(--accent)", values: metricValues },
                  { key: "failed", label: "Failed", color: "#d43d3d", values: daysData.map((d) => d.failed) },
                ]}
              />
            </div>

            <div className="main-cols" style={{ marginTop: 20 }}>
              <div style={{ display: "grid", gap: 20, minWidth: 0 }}>
                <div className="card">
                  <div className="card-header">
                    <h2>Recent Generation Jobs</h2>
                    <span className="spacer" />
                    <a className="link" href="/admin/jobs">View all →</a>
                  </div>
                  {jobTable(recent.data || [])}
                </div>
                <div className="card">
                  <div className="card-header">
                    <h2>Artist Training Queue</h2>
                    <span className="spacer" />
                    <a className="link" href="/admin/training">View all →</a>
                  </div>
                  {(trainings.data || []).map(trainingRow)}
                  {(trainings.data || []).length === 0 && <p style={{ color: "var(--muted)", fontSize: 13 }}>No training runs yet.</p>}
                </div>
              </div>

              <aside style={{ display: "grid", gap: 20, alignContent: "start" }}>
                <div className="card">
                  <div className="card-header">
                    <h2>Model Service Health</h2>
                    <span className="spacer" />
                    <a className="link" href="/admin/services">View all →</a>
                  </div>
                  {(services.data?.services || []).map(serviceRow)}
                </div>
                <div className="card">
                  <div className="card-header">
                    <h2>GPU Workers</h2>
                    <span className="spacer" />
                    <a className="link" href="/admin/workers">Manage →</a>
                  </div>
                  {(workers.data?.workers || []).filter((w) => w.status !== "stale").map(workerRow)}
                  {(workers.data?.workers || []).filter((w) => w.status !== "stale").length === 0 && (
                    <p style={{ color: "var(--muted)" }}>No live workers registered.</p>
                  )}
                  {(workers.data?.workers || []).filter((w) => w.status === "stale").length > 0 && (
                    <p style={{ color: "var(--muted)", fontSize: 12 }}>
                      {(workers.data?.workers || []).filter((w) => w.status === "stale").length} stale historical worker(s).
                    </p>
                  )}
                </div>
              </aside>
            </div>

            <div className="main-cols" style={{ marginTop: 20 }}>
              <div className="card">
                <div className="card-header">
                  <h2>Storage Usage</h2>
                  <span className="spacer" />
                  <a className="link" href="/admin/storage">Manage →</a>
                </div>
                <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
                  <span className="value" style={{ fontSize: 26, fontWeight: 800 }}>{fmtTb(storage.data?.total_bytes ?? 0)}</span>
                  <span style={{ color: "var(--muted)" }}>/ {fmtTb(storage.data?.quota_bytes ?? 5e12)}</span>
                </div>
                <div style={{ marginTop: 8 }}>
                  <Progress value={storage.data ? storage.data.total_bytes / storage.data.quota_bytes : 0} />
                </div>
                <div className="legend" style={{ marginTop: 10 }}>
                  <span><i style={{ background: "var(--accent)" }} />Generated Audio {fmtTb(storage.data?.categories.generated_audio ?? 0)}</span>
                  <span><i style={{ background: "var(--accent-2, #2f6fed)" }} />Training Data {fmtTb(storage.data?.categories.training_data ?? 0)}</span>
                  <span><i style={{ background: "var(--muted)" }} />Checkpoints {fmtTb(storage.data?.categories.model_checkpoints ?? 0)}</span>
                </div>
              </div>
              <div className="card">
                <div className="card-header">
                  <h2>Billing & Credits</h2>
                  <span className="spacer" />
                  <a className="link" href="/admin/billing">View →</a>
                </div>
                <div style={{ display: "flex", gap: 26, flexWrap: "wrap" }}>
                  <div>
                    <div className="label" style={{ color: "var(--muted)", fontSize: 12 }}>Revenue</div>
                    <div style={{ fontSize: 22, fontWeight: 800 }}>${(billing.data?.revenue ?? 0).toLocaleString()}</div>
                  </div>
                  <div>
                    <div className="label" style={{ color: "var(--muted)", fontSize: 12 }}>Credits Used</div>
                    <div style={{ fontSize: 22, fontWeight: 800 }}>{(billing.data?.credits_used ?? 0).toLocaleString()}</div>
                  </div>
                  <div>
                    <div className="label" style={{ color: "var(--muted)", fontSize: 12 }}>Granted</div>
                    <div style={{ fontSize: 22, fontWeight: 800 }}>{(billing.data?.credits_granted ?? 0).toLocaleString()}</div>
                  </div>
                </div>
                <div style={{ marginTop: 10 }}>
                  <Progress value={billing.data ? billing.data.credits_used / billing.data.credits_quota : 0} />
                  <div className="mono" style={{ fontSize: 11, color: "var(--muted)", marginTop: 4 }}>
                    {billing.data?.credits_pct ?? 0}% of {(billing.data?.credits_quota ?? 1e6).toLocaleString()} quota
                  </div>
                </div>
              </div>
            </div>
          </>
        )}

        {section === "users" && (
          <div className="card">
            <div className="card-header">
              <h2>Users ({users.data?.total ?? 0})</h2>
              <span className="spacer" />
              <input style={{ width: 200 }} placeholder="search email or name…" value={userQ} onChange={(e) => setUserQ(e.target.value)} />
            </div>
            <div style={{ display: "flex", gap: 8, marginBottom: 12, flexWrap: "wrap" }}>
              <input style={{ width: 200 }} placeholder="email" value={email} onChange={(e) => setEmail(e.target.value)} />
              <input style={{ width: 130 }} placeholder="username" value={username} onChange={(e) => setUsername(e.target.value)} />
              <input style={{ width: 140 }} type="password" placeholder="password" value={password} onChange={(e) => setPassword(e.target.value)} />
              <button className="btn btn-primary" onClick={() => create.mutate()}>Add User</button>
              {error && <span className="pill err">{error}</span>}
            </div>
            <table className="table">
              <thead><tr><th>User</th><th>Role</th><th>State</th><th>Credits</th></tr></thead>
              <tbody>
                {(users.data?.users || []).map((u) => (
                  <tr key={u.id}>
                    <td><Avatar name={u.username} sm /> {u.username}<div className="mono">{u.email}</div></td>
                    <td><button className="btn" onClick={() => patch.mutate({ id: u.id, body: { role: u.role === "admin" ? "user" : "admin" } })}>{u.role}</button></td>
                    <td><button className="btn" onClick={() => patch.mutate({ id: u.id, body: { state: u.state === "active" ? "disabled" : "active" } })}>{u.state}</button></td>
                    <td>{u.credits_balance.toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {section === "jobs" && (
          <div className="card">
            <div className="card-header">
              <h2>Generation Jobs</h2>
              <span className="spacer" />
              <select style={{ width: 140 }} value={jobStatus} onChange={(e) => setJobStatus(e.target.value)}>
                <option value="">All statuses</option>
                {["queued", "running", "succeeded", "failed", "cancelled"].map((x) => <option key={x} value={x}>{x}</option>)}
              </select>
            </div>
            {jobTable(allJobs.data || [])}
          </div>
        )}

        {section === "services" && (
          <div className="card">
            <div className="card-header"><h2>Model Services</h2></div>
            <table className="table">
              <thead><tr><th>Service</th><th>Status</th><th>Requests 24h</th><th>Avg Latency</th><th>Success</th><th>Uptime</th></tr></thead>
              <tbody>
                {(services.data?.services || []).map((sv) => (
                  <tr key={sv.name}>
                    <td><strong>{sv.name}</strong><div className="mono">{sv.kind} · {sv.version}</div></td>
                    <td><StatusPill status={sv.status} /></td>
                    <td>{sv.requests_24h}</td>
                    <td>{sv.avg_latency_seconds != null ? `${sv.avg_latency_seconds}s` : "—"}</td>
                    <td>{sv.success_rate != null ? `${sv.success_rate}%` : "—"}</td>
                    <td>{sv.uptime_pct}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {section === "workers" && (
          <div className="card">
            <div className="card-header"><h2>GPU Workers</h2></div>
            {(workers.data?.workers || []).map(workerRow)}
            {(workers.data?.workers || []).length === 0 && <p style={{ color: "var(--muted)" }}>No workers registered.</p>}
          </div>
        )}

        {section === "training" && (
          <div className="card">
            <div className="card-header"><h2>Artist Training Queue</h2></div>
            {(trainings.data || []).map(trainingRow)}
            {(trainings.data || []).length === 0 && <p style={{ color: "var(--muted)" }}>No training runs yet.</p>}
          </div>
        )}

        {section === "storage" && storage.data && (
          <div className="card">
            <div className="card-header"><h2>Storage Usage</h2></div>
            {Object.entries({
              "Generated Audio": storage.data.categories.generated_audio,
              "Training Data": storage.data.categories.training_data,
              "Model Checkpoints": storage.data.categories.model_checkpoints,
            }).map(([label, bytes]) => (
              <div key={label} style={{ marginBottom: 12 }}>
                <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13, marginBottom: 4 }}>
                  <strong>{label}</strong>
                  <span className="mono">{fmtTb(bytes)}</span>
                </div>
                <Progress value={storage.data!.total_bytes ? bytes / storage.data!.total_bytes : 0} />
              </div>
            ))}
            <p style={{ color: "var(--muted)", fontSize: 12 }}>
              Total {fmtTb(storage.data.total_bytes)} of {fmtTb(storage.data.quota_bytes)} quota. Model adapters are counted under checkpoints.
            </p>
          </div>
        )}

        {section === "billing" && billing.data && (
          <div className="card">
            <div className="card-header"><h2>Billing & Credits</h2></div>
            <div style={{ display: "flex", gap: 30, flexWrap: "wrap" }}>
              {[
                ["Current Period Revenue", `$${billing.data.revenue.toLocaleString()}`],
                ["Credits Used", `${billing.data.credits_used.toLocaleString()} / ${billing.data.credits_quota.toLocaleString()}`],
                ["Credits Granted", billing.data.credits_granted.toLocaleString()],
                ["Plan", "Production"],
              ].map(([k, v]) => (
                <div key={k}>
                  <div className="label" style={{ color: "var(--muted)", fontSize: 12 }}>{k}</div>
                  <div style={{ fontSize: 22, fontWeight: 800 }}>{v}</div>
                </div>
              ))}
            </div>
            <p style={{ color: "var(--muted)", fontSize: 12, marginTop: 14 }}>
              Subscriptions, API usage, and custom training splits are illustrative until real billing plans land.
            </p>
          </div>
        )}

        {section === "api" && (
          <div className="card">
            <div className="card-header"><h2>API Access</h2></div>
            <p style={{ color: "var(--muted)", fontSize: 13 }}>
              Bearer-token API keys are available today (Authorization: Bearer …). Key management UI is coming soon —
              each API user gets a deterministic token hash for scoping.
            </p>
          </div>
        )}

        {section === "audit" && (
          <div className="card">
            <div className="card-header"><h2>Audit Log</h2></div>
            <table className="table">
              <thead><tr><th>Event</th><th>Job</th><th>Owner</th><th>Operation</th><th>When</th></tr></thead>
              <tbody>
                {(audit.data || []).map((a, i) => (
                  <tr key={i}>
                    <td><StatusPill status={a.status} label={a.event} /></td>
                    <td className="mono">{a.job_id.slice(0, 8)}</td>
                    <td className="mono">{a.owner_id.replace(/^(tok|usr)_/, "").slice(0, 8)}</td>
                    <td>{a.operation}</td>
                    <td className="mono">{a.created_at?.slice(5, 16).replace("T", " ")}</td>
                  </tr>
                ))}
                {(audit.data || []).length === 0 && <tr><td colSpan={5} style={{ color: "var(--muted)" }}>No events yet.</td></tr>}
              </tbody>
            </table>
          </div>
        )}

        {section === "settings" && (
          <div className="card" style={{ maxWidth: 460 }}>
            <div className="card-header"><h2>Settings</h2></div>
            <div className="label" style={{ color: "var(--muted)", fontSize: 12, marginBottom: 6 }}>Site Template</div>
            <select value={site.data?.template || "open-canvas"} onChange={(e) => setTemplate.mutate(e.target.value)}>
              {TEMPLATES.map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
            <p style={{ color: "var(--muted)", fontSize: 12, marginTop: 14 }}>
              Environment and date-range controls are framework placeholders for now.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
