import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, AuthUser, SiteInfo } from "../api";

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
  workers: { id: string; kind: string; drain: boolean; last_heartbeat: string | null }[];
}

const TEMPLATES = ["open-canvas", "analog-soul", "neon-studio", "signal-lab"];

export default function AdminPage() {
  const qc = useQueryClient();
  const me = useQuery({
    queryKey: ["me"],
    queryFn: () => api.get<{ user: AuthUser }>("/api/v1/auth/me"),
    retry: false,
  });
  const users = useQuery({
    queryKey: ["admin-users"],
    queryFn: () => api.get<{ users: AdminUser[]; total: number }>("/api/v1/admin/users"),
    enabled: me.data?.user?.role === "admin",
  });
  const stats = useQuery({
    queryKey: ["admin-stats"],
    queryFn: () => api.get<Stats>("/api/v1/admin/stats"),
    enabled: me.data?.user?.role === "admin",
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
    mutationFn: () =>
      api.post<{ user: AdminUser }>("/api/v1/admin/users", { email, username, password }),
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
  if (me.data.user.role !== "admin")
    return <main className="page"><h1>Admin</h1><p>Admin role required.</p></main>;

  return (
    <main className="page" style={{ display: "grid", gap: 24 }}>
      <h1>Admin Overview</h1>
      <div style={{ display: "flex", gap: 14, flexWrap: "wrap" }}>
        {[
          ["Users", stats.data?.users_total ?? "-"],
          ["Jobs Today", stats.data?.jobs_today ?? "-"],
          ["Active Jobs", stats.data?.jobs_active ?? "-"],
          ["Tracks", stats.data?.assets_total ?? "-"],
        ].map(([label, value]) => (
          <div className="card" key={String(label)} style={{ flex: "1 1 140px" }}>
            <div style={{ color: "var(--muted)", fontSize: 13 }}>{label}</div>
            <div style={{ fontSize: 26, fontWeight: 700 }}>{value}</div>
          </div>
        ))}
      </div>

      <section className="card">
        <h2>Site Template</h2>
        <select
          style={{ width: 200 }}
          value={site.data?.template || "open-canvas"}
          onChange={(e) => setTemplate.mutate(e.target.value)}
        >
          {TEMPLATES.map((t) => (
            <option key={t} value={t}>{t}</option>
          ))}
        </select>
      </section>

      <section className="card">
        <h2>Users ({users.data?.total ?? 0})</h2>
        <div style={{ display: "flex", gap: 8, marginBottom: 12, flexWrap: "wrap" }}>
          <input style={{ width: 200 }} placeholder="email" value={email} onChange={(e) => setEmail(e.target.value)} />
          <input style={{ width: 130 }} placeholder="username" value={username} onChange={(e) => setUsername(e.target.value)} />
          <input style={{ width: 140 }} type="password" placeholder="password" value={password} onChange={(e) => setPassword(e.target.value)} />
          <button className="primary" onClick={() => create.mutate()}>Add User</button>
          {error && <span style={{ color: "crimson" }}>{error}</span>}
        </div>
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead>
            <tr style={{ textAlign: "left", color: "var(--muted)", fontSize: 13 }}>
              <th>User</th><th>Role</th><th>State</th><th>Credits</th><th />
            </tr>
          </thead>
          <tbody>
            {(users.data?.users || []).map((u) => (
              <tr key={u.id} style={{ borderTop: "1px solid var(--border)" }}>
                <td>{u.username}<div style={{ color: "var(--muted)", fontSize: 12 }}>{u.email}</div></td>
                <td>
                  <button onClick={() => patch.mutate({ id: u.id, body: { role: u.role === "admin" ? "user" : "admin" } })}>
                    {u.role}
                  </button>
                </td>
                <td>
                  <button onClick={() => patch.mutate({ id: u.id, body: { state: u.state === "active" ? "disabled" : "active" } })}>
                    {u.state}
                  </button>
                </td>
                <td>{u.credits_balance}</td>
                <td />
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="card">
        <h2>GPU Workers</h2>
        {(stats.data?.workers || []).map((w) => (
          <div key={w.id} style={{ marginBottom: 6 }}>
            {w.id} — {w.kind} {w.drain ? "(draining)" : ""}
          </div>
        ))}
        {(stats.data?.workers || []).length === 0 && <p style={{ color: "var(--muted)" }}>No workers registered.</p>}
      </section>
    </main>
  );
}
