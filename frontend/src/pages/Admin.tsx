import { useState } from "react";
import { NavLink } from "react-router-dom";
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
  jobs_today: number;
  jobs_active: number;
  assets_total: number;
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
interface AdminJob {
  job_id: string;
  owner_id: string;
  operation: string;
  status: string;
  stage?: string | null;
  progress?: number | null;
  error_code?: string | null;
  created_at: string | null;
  started_at: string | null;
  finished_at: string | null;
}

const SIDEBAR = [
  { label: "Overview", icon: "⌂" },
  { label: "Users", icon: "☺" },
  { label: "Generation Jobs", icon: "⇍" },
  { label: "GPU Workers", icon: "▦" },
  { label: "Artist Training", icon: "◈" },
  { label: "Settings", icon: "⚙" },
];

const TEMPLATES = ["open-canvas", "analog-soul", "neon-studio", "signal-lab"];

function runtime(j: AdminJob): string {
  if (!j.started_at || !j.finished_at) return j.status === "running" ? "…" : "—";
  const secs = (new Date(j.finished_at).getTime() - new Date(j.started_at).getTime()) / 1000;
  return secs >= 60 ? `${Math.floor(secs / 60)}m ${Math.round(secs % 60)}s` : `${Math.round(secs)}s`;
}

export default function AdminPage() {
  const qc = useQueryClient();
  const me = useQuery({
    queryKey: ["me"],
    queryFn: () => api.get<{ user: AuthUser }>("/api/v1/auth/me"),
    retry: false,
  });
  const isAdmin = me.data?.user?.role === "admin";
  const users = useQuery({
    queryKey: ["admin-users"],
    queryFn: () => api.get<{ users: AdminUser[]; total: number }>("/api/v1/admin/users"),
    enabled: isAdmin,
  });
  const stats = useQuery({
    queryKey: ["admin-stats"],
    queryFn: () => api.get<Stats>("/api/v1/admin/stats"),
    enabled: isAdmin,
    refetchInterval: 15000,
  });
  const series = useQuery({
    queryKey: ["admin-timeseries"],
    queryFn: () => api.get<{ days: number; series: DayPoint[] }>("/api/v1/admin/stats/timeseries?days=14"),
    enabled: isAdmin,
    refetchInterval: 60000,
  });
  const recent = useQuery({
    queryKey: ["admin-jobs"],
    queryFn: () => api.get<AdminJob[]>("/api/v1/admin/jobs?limit=8"),
    enabled: isAdmin,
    refetchInterval: 10000,
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

  const days = series.data?.series || [];
  const labels = days.map((d) => d.date);
  const completed = days.map((d) => d.completed);
  const newUsers = days.map((d) => d.new_users);
  const firstHalf = completed.slice(0, Math.floor(completed.length / 2));
  const secondHalf = completed.slice(Math.floor(completed.length / 2));
  const jobsDelta =
    firstHalf.length && secondHalf.length && firstHalf.reduce((a, b) => a + b, 0) > 0
      ? Math.round(
          ((secondHalf.reduce((a, b) => a + b, 0) - firstHalf.reduce((a, b) => a + b, 0)) /
            firstHalf.reduce((a, b) => a + b, 0)) *
            100
        )
      : 0;

  return (
    <div className="dash">
      <aside className="dash-sidebar">
        {SIDEBAR.map((s, i) => (
          <NavLink key={s.label} to="/admin" className={i === 0 ? "active" : ""}>
            <span aria-hidden>{s.icon}</span> {s.label}
          </NavLink>
        ))}
        <div className="side-note">OpenAudioLab — platform operations.</div>
      </aside>
      <div className="dash-main">
        <div className="hero-strip">
          <h1>Admin Overview</h1>
          <div className="sub">Monitor platform health, usage, and operations in real time.</div>
        </div>

        <div className="stat-grid">
          <div className="card stat-card">
            <span className="icon">☺</span>
            <div>
              <div className="label">Active Users</div>
              <div className="value">{stats.data?.users_total ?? "-"}</div>
            </div>
            <span className="chart"><Sparkline values={newUsers.length ? newUsers : [0, 0]} /></span>
          </div>
          <div className="card stat-card">
            <span className="icon">⇍</span>
            <div>
              <div className="label">Jobs Today</div>
              <div className="value">{stats.data?.jobs_today ?? "-"}</div>
              <Delta value={jobsDelta} vs="vs. prior week" />
            </div>
            <span className="chart"><Sparkline values={completed.length ? completed : [0, 0]} /></span>
          </div>
          <div className="card stat-card">
            <span className="icon">▦</span>
            <div>
              <div className="label">Active Jobs</div>
              <div className="value">{stats.data?.jobs_active ?? "-"}</div>
              <div className="sub">queued + running</div>
            </div>
          </div>
          <div className="card stat-card">
            <span className="icon">◎</span>
            <div>
              <div className="label">Tracks Stored</div>
              <div className="value">{stats.data?.assets_total ?? "-"}</div>
            </div>
          </div>
        </div>

        <div className="card" style={{ marginTop: 20 }}>
          <div className="card-header">
            <h2>Generation Activity</h2>
            <span className="sub" style={{ color: "var(--muted)", fontSize: 13 }}>jobs per day, last 14 days</span>
            <span className="spacer" />
            <div className="segmented">
              <button type="button" className="active">Daily</button>
            </div>
          </div>
          <AreaChart
            labels={labels}
            series={[
              { key: "completed", label: "Completed", color: "var(--accent)", values: completed },
              { key: "active", label: "Active", color: "var(--accent-2, #2f6fed)", values: days.map((d) => d.active) },
              { key: "failed", label: "Failed", color: "#d43d3d", values: days.map((d) => d.failed) },
            ]}
          />
        </div>

        <div className="main-cols" style={{ marginTop: 20 }}>
          <div style={{ display: "grid", gap: 20, minWidth: 0 }}>
            <div className="card">
              <div className="card-header">
                <h2>Recent Generation Jobs</h2>
                <span className="spacer" />
                <a className="link" href="/admin">View all →</a>
              </div>
              <table className="table">
                <thead>
                  <tr>
                    <th>Job ID</th><th>User</th><th>Task</th><th>Status</th><th>Runtime</th><th>Created</th>
                  </tr>
                </thead>
                <tbody>
                  {(recent.data || []).map((j) => (
                    <tr key={j.job_id}>
                      <td className="mono">{j.job_id.slice(0, 8)}</td>
                      <td><Avatar name={j.owner_id} sm /> {j.owner_id.replace(/^(tok|usr)_/, "").slice(0, 6)}</td>
                      <td>{j.operation}</td>
                      <td><StatusPill status={j.status} /></td>
                      <td>{runtime(j)}</td>
                      <td className="mono">{j.created_at?.slice(5, 16).replace("T", " ")}</td>
                    </tr>
                  ))}
                  {(recent.data || []).length === 0 && (
                    <tr><td colSpan={6} style={{ color: "var(--muted)" }}>No jobs yet.</td></tr>
                  )}
                </tbody>
              </table>
            </div>

            <div className="card">
              <div className="card-header">
                <h2>Users ({users.data?.total ?? 0})</h2>
              </div>
              <div style={{ display: "flex", gap: 8, marginBottom: 12, flexWrap: "wrap" }}>
                <input style={{ width: 200 }} placeholder="email" value={email} onChange={(e) => setEmail(e.target.value)} />
                <input style={{ width: 130 }} placeholder="username" value={username} onChange={(e) => setUsername(e.target.value)} />
                <input style={{ width: 140 }} type="password" placeholder="password" value={password} onChange={(e) => setPassword(e.target.value)} />
                <button className="btn btn-primary" onClick={() => create.mutate()}>Add User</button>
                {error && <span className="pill err">{error}</span>}
              </div>
              <table className="table">
                <thead>
                  <tr><th>User</th><th>Role</th><th>State</th><th>Credits</th></tr>
                </thead>
                <tbody>
                  {(users.data?.users || []).map((u) => (
                    <tr key={u.id}>
                      <td><Avatar name={u.username} sm /> {u.username}<div className="mono">{u.email}</div></td>
                      <td>
                        <button className="btn" onClick={() => patch.mutate({ id: u.id, body: { role: u.role === "admin" ? "user" : "admin" } })}>
                          {u.role}
                        </button>
                      </td>
                      <td>
                        <button className="btn" onClick={() => patch.mutate({ id: u.id, body: { state: u.state === "active" ? "disabled" : "active" } })}>
                          {u.state}
                        </button>
                      </td>
                      <td>{u.credits_balance.toLocaleString()}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <aside style={{ display: "grid", gap: 20, alignContent: "start" }}>
            <div className="card">
              <div className="card-header">
                <h2>GPU Workers</h2>
              </div>
              {(stats.data?.workers || [])
                .filter((w) => w.kind === "acestep")
                .map((w) => {
                const fresh =
                  w.last_heartbeat != null && Date.now() - new Date(w.last_heartbeat + "Z").getTime() < 120000;
                const vramPct = w.vram_used_mb && w.vram_total_mb ? w.vram_used_mb / w.vram_total_mb : 0;
                return (
                  <div key={w.id} style={{ marginBottom: 14 }}>
                    <div style={{ display: "flex", justifyContent: "space-between", gap: 8, fontSize: 13, marginBottom: 4 }}>
                      <strong>{w.id}</strong>
                      <StatusPill status={w.drain ? "draining" : fresh ? "online" : "offline"} label={fresh ? "online" : w.drain ? "draining" : "stale"} />
                    </div>
                    <div style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 12, color: "var(--muted)" }}>
                      <span style={{ width: 34 }}>{w.gpu_util != null ? `${w.gpu_util}%` : "—"}</span>
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
              })}
              {(stats.data?.workers || []).filter((w) => w.kind === "acestep").length === 0 && (
                <p style={{ color: "var(--muted)" }}>No GPU workers registered.</p>
              )}
            </div>

            <div className="card">
              <div className="card-header">
                <h2>Site Template</h2>
              </div>
              <select value={site.data?.template || "open-canvas"} onChange={(e) => setTemplate.mutate(e.target.value)}>
                {TEMPLATES.map((t) => (
                  <option key={t} value={t}>{t}</option>
                ))}
              </select>
            </div>
          </aside>
        </div>
      </div>
    </div>
  );
}
