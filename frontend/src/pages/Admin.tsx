import { useEffect, useState } from "react";
import { NavLink, useLocation, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, AuthUser, SiteInfo } from "../api";
import { AreaChart, BarChart, Sparkline } from "../components/charts";
import { Avatar, Delta, Progress, StatusPill } from "../components/ui";

interface AdminUser {
  id: string;
  email: string;
  username: string;
  role: string;
  state: string;
  plan: string;
  credits_balance: number;
  jobs_count: number;
  stripe_customer_id: string | null;
}
interface Page<T> {
  items: T[];
  total: number;
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
  profile_version_id: string | null;
  user: string;
  status: string;
  stage: string | null;
  progress: number | null;
  eta_seconds: number | null;
  created_at: string | null;
  hardware: string | null;
  error: string | null;
  suggested_tags?: string[];
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
interface JobDetail extends AdminJob {
  error_message?: string | null;
  events: { event: string; status: string; stage: string | null; created_at: string | null }[];
}
interface StorageInfo {
  total_bytes: number;
  quota_bytes: number;
  categories: { generated_audio: number; training_data: number; model_checkpoints: number; other: number };
}
interface Billing {
  revenue: number;
  revenue_delta_pct: number;
  subscribers?: number;
  credits_used: number;
  credits_granted: number;
  credits_quota: number;
  credits_pct: number;
  subscriptions_pct: number;
  api_usage_pct: number;
  custom_training_pct: number;
  export_pct?: number;
  job_counts?: Record<string, number>;
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
interface AdminErrorRow {
  id: number;
  component: string;
  route: string | null;
  http_status: number | null;
  error_code: string;
  message: string;
  job_id: string | null;
  worker_id: string | null;
  resolved: boolean;
  created_at: string | null;
}
interface AdminErrorDetail extends AdminErrorRow {
  traceback: string | null;
  context_json: Record<string, unknown>;
  user_id: string | null;
  fingerprint: string | null;
  agent_brief: string;
}
interface PricingRow {
  id: string;
  kind: string;
  name: string;
  price_usd: number;
  credits: number;
  position: number;
}
interface CreditRow {
  id: string;
  owner_id: string;
  user: string;
  delta: number;
  reason: string;
  job_id: string | null;
  created_at: string | null;
}
interface KeyRow {
  id: string;
  name: string;
  prefix: string;
  created_at: string;
  revoked_at: string | null;
  last_used_at: string | null;
  secret?: string;
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

interface VastInstanceRow {
  id: string;
  vast_instance_id: string;
  role: string;
  gpu_model: string | null;
  state: string;
  live_status: string | null;
  last_used_at: string | null;
  stopped_at: string | null;
}

const SIDEBAR = [
  { to: "/admin", label: "Overview", icon: "⌂" },
  { to: "/admin/users", label: "Users", icon: "☺" },
  { to: "/admin/jobs", label: "Generation Jobs", icon: "⇍" },
  { to: "/admin/services", label: "Model Services", icon: "▣" },
  { to: "/admin/workers", label: "GPU Workers", icon: "▦" },
  { to: "/admin/vast", label: "Vast Cloud", icon: "☁" },
  { to: "/admin/training", label: "Artist Training", icon: "◈" },
  { to: "/admin/loras", label: "Style Models", icon: "♪" },
  { to: "/admin/storage", label: "Storage", icon: "▤" },
  { to: "/admin/billing", label: "Billing", icon: "▥" },
  { to: "/admin/api", label: "API Access", icon: "</>" },
  { to: "/admin/errors", label: "Errors", icon: "⚠" },
  { to: "/admin/pricing", label: "Pricing", icon: "$" },
  { to: "/admin/audit", label: "Audit Log", icon: "▦" },
  { to: "/admin/settings", label: "Settings", icon: "⚙" },
];

const TEMPLATES = ["open-canvas", "analog-soul", "neon-studio", "signal-lab"];
const ENVIRONMENTS = ["production", "staging", "development"];
const TASK_OPTIONS = [
  { value: "", label: "All tasks" },
  { value: "music.generate", label: "Text to Music" },
  { value: "audio.export", label: "Audio Export" },
  { value: "artist.train", label: "Artist Training" },
];

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
  const [params] = useSearchParams();
  const section = location.pathname.replace(/^\/admin\/?/, "") || "overview";

  const [days, setDays] = useState(14);
  const [granularity, setGranularity] = useState<"day" | "hour">("day");
  const [task, setTask] = useState("all");
  const [metric, setMetric] = useState<"tracks" | "users" | "compute">("tracks");
  const [userQ, setUserQ] = useState("");
  const [userOffset, setUserOffset] = useState(0);
  const [ledgerFor, setLedgerFor] = useState<AdminUser | null>(null);
  const [adjDelta, setAdjDelta] = useState("");
  const [adjNote, setAdjNote] = useState("");
  const [jobStatus, setJobStatus] = useState("");
  const [jobTask, setJobTask] = useState(params.get("task") || "");
  const [jobLimit, setJobLimit] = useState(25);
  const [auditEvent, setAuditEvent] = useState("");
  const [auditLimit, setAuditLimit] = useState(50);
  const [detailId, setDetailId] = useState<string | null>(null);
  const [errorId, setErrorId] = useState<number | null>(null);
  const [creditDraft, setCreditDraft] = useState<{ id: string; value: string } | null>(null);
  const [keyName, setKeyName] = useState("");
  const [newSecret, setNewSecret] = useState<string | null>(null);
  const [, setTick] = useState(0);

  useEffect(() => {
    setJobTask(params.get("task") || "");
    setJobLimit(25);
  }, [params]);

  useEffect(() => {
    setUserOffset(0);
  }, [userQ]);

  useEffect(() => {
    const t = setInterval(() => setTick((x) => x + 1), 5000);
    return () => clearInterval(t);
  }, []);

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
    queryFn: () => api.get<Page<AdminJob>>("/api/v1/admin/jobs?limit=8"),
    enabled,
    refetchInterval: 10000,
  });
  const allJobs = useQuery({
    queryKey: ["admin-jobs", "all", jobStatus, jobTask, jobLimit],
    queryFn: () =>
      api.get<Page<AdminJob>>(
        `/api/v1/admin/jobs?limit=${jobLimit}${jobStatus ? `&status=${jobStatus}` : ""}${jobTask ? `&task=${jobTask}` : ""}`
      ),
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
  const vast = useQuery({
    queryKey: ["admin-vast"],
    queryFn: () => api.get<{ instances: VastInstanceRow[]; live_available: boolean }>("/api/v1/admin/vast/instances"),
    enabled: enabled && section === "vast",
    refetchInterval: 15000,
  });
  const [loraName, setLoraName] = useState("");
  const [loraTags, setLoraTags] = useState("");
  const [loraFiles, setLoraFiles] = useState<FileList | null>(null);
  const [loraProgress, setLoraProgress] = useState<number | null>(null);
  const loras = useQuery({
    queryKey: ["admin-loras"],
    queryFn: () => api.get<{ loras: { id: string; name: string; tags: string[]; state: string; auto_apply: boolean; priority: number; default_scale: number; provenance: string; profile_version_id: string | null; training_status: string | null }[] }>("/api/v1/admin/loras"),
    enabled: enabled && section === "loras",
  });
  const invalidateLoras = () => {
    qc.invalidateQueries({ queryKey: ["admin-loras"] });
    qc.invalidateQueries({ queryKey: ["admin-trainings"] });
  };
  const uploadLora = useMutation({
    mutationFn: () =>
      new Promise<{ titles: string[] }>((resolve, reject) => {
        const fd = new FormData();
        fd.append("name", loraName);
        fd.append("tags", loraTags);
        Array.from(loraFiles || []).forEach((f) => fd.append("files", f));
        const xhr = new XMLHttpRequest();
        xhr.open("POST", "/api/v1/admin/loras/upload");
        xhr.withCredentials = true;
        xhr.upload.onprogress = (e) => setLoraProgress(e.lengthComputable ? Math.round((e.loaded / e.total) * 100) : null);
        xhr.onload = () => {
          let data: any = {};
          try { data = JSON.parse(xhr.responseText); } catch { /* keep default */ }
          if (xhr.status >= 200 && xhr.status < 300) resolve(data);
          else reject(new Error(data?.error?.message || `Upload failed (HTTP ${xhr.status})`));
        };
        xhr.onerror = () => reject(new Error("Upload failed (network)"));
        xhr.send(fd);
      }),
    onSuccess: () => { setLoraName(""); setLoraTags(""); setLoraFiles(null); setLoraProgress(null); invalidateLoras(); },
    onError: (e: Error) => { setLoraProgress(null); setError(e.message); },
  });
  const publishLora = useMutation({
    mutationFn: (t: Training) =>
      api.post<{ id: string }>("/api/v1/admin/loras", {
        profile_version_id: t.profile_version_id,
        name: `${t.profile} style`,
        tags: [t.profile.toLowerCase().replace(/\s+/g, "-"), ...(t.suggested_tags || [])].join(","),
      }),
    onSuccess: invalidateLoras,
  });
  const patchLora = useMutation({
    mutationFn: ({ id, body }: { id: string; body: Record<string, unknown> }) => api.patch(`/api/v1/admin/loras/${id}`, body),
    onSuccess: invalidateLoras,
  });
  const deleteLora = useMutation({
    mutationFn: async (id: string) => {
      const res = await fetch(`/api/v1/admin/loras/${id}`, { method: "DELETE", credentials: "include" });
      if (!res.ok) throw new Error(`Delete failed (${res.status})`);
      return res.status === 204 ? null : res.json().catch(() => null);
    },
    onSuccess: invalidateLoras,
    onError: (e: Error) => setError(e.message),
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
  const credits = useQuery({
    queryKey: ["admin-credits", auditLimit],
    queryFn: () => api.get<Page<CreditRow>>(`/api/v1/admin/credits?limit=${Math.min(auditLimit, 100)}`),
    enabled: enabled && section === "billing",
  });
  const audit = useQuery({
    queryKey: ["admin-audit", auditEvent, auditLimit],
    queryFn: () =>
      api.get<Page<AuditRow>>(`/api/v1/admin/audit?limit=${auditLimit}${auditEvent ? `&event=${encodeURIComponent(auditEvent)}` : ""}`),
    enabled: enabled && section === "audit",
  });
  const ledger = useQuery({
    queryKey: ["admin-user-credits", ledgerFor?.id],
    queryFn: () => api.get<{ entries: { id: string; delta: number; reason: string; note: string | null; created_at: string | null }[] }>(`/api/v1/admin/users/${ledgerFor?.id}/credits`),
    enabled: !!ledgerFor,
  });
  const adjust = useMutation({
    mutationFn: () =>
      api.post<{ credits_balance: number }>(`/api/v1/admin/users/${ledgerFor?.id}/credits`, {
        delta: Number(adjDelta),
        reason: "admin_adjust",
        note: adjNote || null,
      }),
    onSuccess: () => {
      setAdjDelta("");
      setAdjNote("");
      qc.invalidateQueries({ queryKey: ["admin-user-credits", ledgerFor?.id] });
      qc.invalidateQueries({ queryKey: ["admin-users"] });
    },
  });

  const users = useQuery({
    queryKey: ["admin-users", userQ, userOffset],
    queryFn: () =>
      api.get<{ users: AdminUser[]; total: number }>(
        `/api/v1/admin/users?limit=50&offset=${userOffset}${userQ ? `&q=${encodeURIComponent(userQ)}` : ""}`
      ),
    enabled,
  });
  const site = useQuery({ queryKey: ["site"], queryFn: () => api.get<SiteInfo>("/api/v1/site") });
  const settings = useQuery({
    queryKey: ["admin-settings"],
    queryFn: () => api.get<{ settings: Record<string, string> }>("/api/v1/admin/settings"),
    enabled,
  });
  const keys = useQuery({
    queryKey: ["api-keys"],
    queryFn: () => api.get<{ items: KeyRow[] }>("/api/v1/api-keys"),
    enabled: enabled && section === "api",
  });
  const detail = useQuery({
    queryKey: ["admin-job-detail", detailId],
    queryFn: () => api.get<JobDetail>(`/api/v1/admin/jobs/${detailId}`),
    enabled: !!detailId,
    refetchInterval: detailId ? 5000 : false,
  });

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
    mutationFn: ({ id, body }: { id: string; body: Record<string, string | number> }) =>
      api.patch(`/api/v1/admin/users/${id}`, body),
    onSuccess: invalidate,
  });
  const setTemplate = useMutation({
    mutationFn: (value: string) => api.put("/api/v1/admin/settings/template", { value }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["site"] });
      qc.invalidateQueries({ queryKey: ["admin-settings"] });
    },
  });
  const setEnvironment = useMutation({
    mutationFn: (value: string) => api.put("/api/v1/admin/settings/environment", { value }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin-settings"] }),
  });
  const drain = useMutation({
    mutationFn: (id: string) => api.post<{ drain: boolean }>(`/api/v1/admin/workers/${id}/drain`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin-workers"] }),
  });
  const purge = useMutation({
    mutationFn: () => api.del<{ purged: number }>("/api/v1/admin/workers/stale"),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin-workers"] }),
  });
  const vastAction = useMutation({
    mutationFn: ({ id, action }: { id: string; action: string }) =>
      api.post<{ ok: boolean }>(`/api/v1/admin/vast/instances/${id}/action`, { action }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin-vast"] }),
  });
  const cancelTraining = useMutation({
    mutationFn: (id: string) => api.post<{ status: string }>(`/api/v1/admin/trainings/${id}/cancel`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin-trainings"] }),
  });
  const deleteUser = useMutation({
    mutationFn: (id: string) => api.delete(`/api/v1/admin/users/${id}`),
    onSuccess: invalidate,
  });

  const [errorsLimit, setErrorsLimit] = useState(10);
  const errors = useQuery({
    queryKey: ["admin-errors", errorsLimit],
    queryFn: () =>
      api.get<{ items: AdminErrorRow[]; total: number }>(`/api/v1/admin/errors?limit=${errorsLimit}`),
    enabled: enabled && section === "errors",
    refetchInterval: section === "errors" ? 10000 : false,
  });
  const errorDetail = useQuery({
    queryKey: ["admin-error-detail", errorId],
    queryFn: () => api.get<AdminErrorDetail>(`/api/v1/admin/errors/${errorId}`),
    enabled: !!errorId,
  });
  const resolveError = useMutation({
    mutationFn: ({ id, resolved }: { id: number; resolved: boolean }) =>
      api.patch(`/api/v1/admin/errors/${id}`, { resolved }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin-errors"] });
      qc.invalidateQueries({ queryKey: ["admin-error-detail", errorId] });
    },
  });

  const pricing = useQuery({
    queryKey: ["admin-pricing"],
    queryFn: () => api.get<{ plan: PricingRow[]; pack: PricingRow[] }>("/api/v1/admin/pricing"),
    enabled: enabled && section === "pricing",
  });
  const [pricingDraft, setPricingDraft] = useState<PricingRow[] | null>(null);
  const savePricing = useMutation({
    mutationFn: (items: PricingRow[]) =>
      api.put<{ plan: PricingRow[]; pack: PricingRow[] }>("/api/v1/admin/pricing", { items }),
    onSuccess: () => {
      setPricingDraft(null);
      qc.invalidateQueries({ queryKey: ["admin-pricing"] });
    },
  });
  const createKey = useMutation({
    mutationFn: () => api.post<KeyRow>("/api/v1/api-keys", { name: keyName || "default" }),
    onSuccess: (k) => {
      setNewSecret(k.secret || null);
      setKeyName("");
      qc.invalidateQueries({ queryKey: ["api-keys"] });
    },
  });
  const revokeKey = useMutation({
    mutationFn: (id: string) => api.del<KeyRow>(`/api/v1/api-keys/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["api-keys"] }),
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
  const updatedAgo = stats.dataUpdatedAt ? Math.max(0, Math.round((Date.now() - stats.dataUpdatedAt) / 1000)) : null;
  const envValue = settings.data?.settings?.environment || "production";

  const jobTable = (rows: AdminJob[]) => (
    <table className="table">
      <thead>
        <tr><th>Job ID</th><th>User</th><th>Task</th><th>Status</th><th>Runtime</th><th>Created</th></tr>
      </thead>
      <tbody>
        {rows.map((j) => (
          <tr key={j.job_id}>
            <td><button className="link mono" style={{ border: 0, background: "none", cursor: "pointer", padding: 0, font: "inherit" }} onClick={() => setDetailId(j.job_id)}>{j.job_id.slice(0, 8)}</button></td>
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
        <a className="link" href={`/admin/jobs?task=${sv.operation}`}>{sv.name}</a>
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
          <span style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <StatusPill status={w.status === "stale" ? "failed" : w.status === "draining" ? "cancelled" : "online"} label={w.status} />
            {section === "workers" && w.status !== "stale" && (
              <button className="btn" onClick={() => drain.mutate(w.id)}>{w.drain ? "Resume" : "Drain"}</button>
            )}
          </span>
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
        <span style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <StatusPill status={t.status} />
          {section === "training" && (t.status === "queued" || t.status === "running") && (
            <button className="btn" onClick={() => cancelTraining.mutate(t.run_id)}>Cancel</button>
          )}
        </span>
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
            <div className="sub">
              Monitor platform health, usage, and operations in real time.
              {updatedAgo != null && <span className="mono"> · updated {updatedAgo}s ago</span>}
            </div>
          </div>
          <div className="strip-controls">
            <select value={envValue} onChange={(e) => setEnvironment.mutate(e.target.value)} title="Deployment environment">
              {ENVIRONMENTS.map((e) => <option key={e} value={e}>● {e[0].toUpperCase() + e.slice(1)}</option>)}
            </select>
            <select value={days} onChange={(e) => setDays(Number(e.target.value))} title="Chart date range">
              {[7, 14, 30].map((d) => <option key={d} value={d}>Last {d} days</option>)}
            </select>
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
              </div>
              {granularity === "hour" ? (
                <BarChart
                  labels={labels}
                  series={[
                    { key: "metric", label: metric === "tracks" ? "Completed" : metric === "users" ? "New Users" : "Active", color: "var(--accent)", values: metricValues },
                    { key: "failed", label: "Failed", color: "#d43d3d", values: daysData.map((d) => d.failed) },
                  ]}
                />
              ) : (
                <AreaChart
                  labels={labels}
                  series={[
                    { key: "metric", label: metric === "tracks" ? "Completed" : metric === "users" ? "New Users" : "Active", color: "var(--accent)", values: metricValues },
                    { key: "failed", label: "Failed", color: "#d43d3d", values: daysData.map((d) => d.failed) },
                  ]}
                />
              )}
            </div>

            <div className="main-cols" style={{ marginTop: 20 }}>
              <div style={{ display: "grid", gap: 20, minWidth: 0 }}>
                <div className="card">
                  <div className="card-header">
                    <h2>Recent Generation Jobs</h2>
                    <span className="spacer" />
                    <a className="link" href="/admin/jobs">View all →</a>
                  </div>
                  {jobTable(recent.data?.items || [])}
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
              <thead><tr><th>User</th><th>Role</th><th>State</th><th>Plan</th><th>Jobs</th><th>Credits</th><th /></tr></thead>
              <tbody>
                {(users.data?.users || []).map((u) => (
                  <tr key={u.id}>
                    <td><Avatar name={u.username} sm /> {u.username}<div className="mono">{u.email}</div></td>
                    <td><button className="btn" onClick={() => patch.mutate({ id: u.id, body: { role: u.role === "admin" ? "user" : "admin" } })}>{u.role}</button></td>
                    <td><button className="btn" onClick={() => patch.mutate({ id: u.id, body: { state: u.state === "active" ? "disabled" : "active" } })}>{u.state}</button></td>
                    <td>
                      <button
                        className="btn"
                        title="Cycle plan"
                        onClick={() => patch.mutate({ id: u.id, body: { plan: u.plan === "free" ? "pro" : u.plan === "pro" ? "premier" : "free" } })}
                      >
                        {u.plan}
                      </button>
                    </td>
                    <td>{u.jobs_count}</td>
                    <td>
                      {creditDraft?.id === u.id ? (
                        <span style={{ display: "inline-flex", gap: 6, alignItems: "center" }}>
                          <input
                            style={{ width: 90 }}
                            type="number"
                            min={0}
                            value={creditDraft.value}
                            autoFocus
                            onChange={(e) => setCreditDraft({ id: u.id, value: e.target.value })}
                            onKeyDown={(e) => {
                              if (e.key === "Enter") {
                                patch.mutate({ id: u.id, body: { credits_balance: Number(creditDraft.value) } });
                                setCreditDraft(null);
                              }
                              if (e.key === "Escape") setCreditDraft(null);
                            }}
                          />
                          <button
                            className="btn"
                            onClick={() => {
                              patch.mutate({ id: u.id, body: { credits_balance: Number(creditDraft.value) } });
                              setCreditDraft(null);
                            }}
                          >set</button>
                        </span>
                      ) : (
                        <button
                          className="btn"
                          title="Click to adjust credits"
                          onClick={() => setCreditDraft({ id: u.id, value: String(u.credits_balance) })}
                        >
                          {u.credits_balance.toLocaleString()}
                        </button>
                      )}
                    </td>
                    <td><button className="btn btn-ghost" onClick={() => setLedgerFor(u)}>ledger</button></td>
                    <td>
                      <button
                        className="btn btn-ghost"
                        title="Soft-delete (purged after 30 days)"
                        onClick={() => window.confirm(`Delete ${u.username}?`) && deleteUser.mutate(u.id)}
                      >
                        ✕
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 10 }}>
              <button className="btn" disabled={userOffset === 0} onClick={() => setUserOffset((n) => Math.max(0, n - 50))}>Prev</button>
              <span className="sub">
                {Math.min(userOffset + 1, users.data?.total ?? 0)}–{Math.min(userOffset + (users.data?.users.length ?? 0), users.data?.total ?? 0)} of {users.data?.total ?? 0}
              </span>
              <button className="btn" disabled={userOffset + (users.data?.users.length ?? 0) >= (users.data?.total ?? 0)} onClick={() => setUserOffset((n) => n + 50)}>Next</button>
            </div>
          </div>
        )}

        {ledgerFor && (
          <div className="drawer-overlay" onClick={() => setLedgerFor(null)}>
            <div className="drawer" onClick={(e) => e.stopPropagation()}>
              <div className="card-header">
                <h2>{ledgerFor.username} — billing</h2>
                <span className="spacer" />
                <button className="btn" onClick={() => setLedgerFor(null)}>Close</button>
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "6px 16px", fontSize: 13, marginBottom: 12 }}>
                <span className="muted">Email</span><span>{ledgerFor.email}</span>
                <span className="muted">Plan</span><span>{ledgerFor.plan}</span>
                <span className="muted">Balance</span><span>{ledgerFor.credits_balance.toLocaleString()} cr</span>
                <span className="muted">Stripe customer</span><span className="mono">{ledgerFor.stripe_customer_id || "—"}</span>
              </div>
              <div style={{ display: "flex", gap: 8, marginBottom: 14, flexWrap: "wrap" }}>
                <input style={{ width: 90 }} type="number" placeholder="+/-" value={adjDelta} onChange={(e) => setAdjDelta(e.target.value)} />
                <input style={{ width: 180 }} placeholder="note (optional)" value={adjNote} onChange={(e) => setAdjNote(e.target.value)} />
                <button className="btn btn-primary" disabled={!adjDelta || adjust.isPending} onClick={() => adjust.mutate()}>
                  {Number(adjDelta) >= 0 ? "Grant" : "Deduct"}
                </button>
              </div>
              <table className="table">
                <thead><tr><th>When</th><th>Delta</th><th>Reason</th><th>Note</th></tr></thead>
                <tbody>
                  {(ledger.data?.entries || []).map((e) => (
                    <tr key={e.id}>
                      <td className="mono">{e.created_at?.slice(0, 16).replace("T", " ")}</td>
                      <td style={{ color: e.delta >= 0 ? "var(--ok, green)" : "var(--err, red)" }}>{e.delta >= 0 ? "+" : ""}{e.delta.toLocaleString()}</td>
                      <td>{e.reason}</td>
                      <td>{e.note || ""}</td>
                    </tr>
                  ))}
                  {ledger.data && ledger.data.entries.length === 0 && <tr><td colSpan={4} style={{ color: "var(--muted)" }}>No ledger entries yet.</td></tr>}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {section === "loras" && (
          <div className="card">
            <div className="card-header">
              <h2>Style models (LoRA)</h2>
              <span className="spacer" />
              <span className="sub" style={{ fontSize: 12 }}>Upload song files — the title is read from the filename and used as a style keyword</span>
            </div>
            <div style={{ display: "flex", gap: 8, marginBottom: 14, flexWrap: "wrap", alignItems: "center" }}>
              <input style={{ width: 180 }} placeholder="style model name" value={loraName} onChange={(e) => setLoraName(e.target.value)} />
              <input style={{ width: 200 }} placeholder="tags (comma separated)" value={loraTags} onChange={(e) => setLoraTags(e.target.value)} />
              <input type="file" accept="audio/*" multiple onChange={(e) => setLoraFiles(e.target.files)} />
              <button
                className="btn btn-primary"
                disabled={!loraName || !loraFiles?.length || uploadLora.isPending}
                onClick={() => uploadLora.mutate()}
              >
                {uploadLora.isPending ? (loraProgress !== null ? `Uploading ${loraProgress}%` : "Uploading…") : "Upload & train"}
              </button>
              {error && <span className="pill err">{error}</span>}
            </div>
            {(() => {
              const t = (trainings.data || [])[0];
              if (!t) return null;
              const published = (loras.data?.loras || []).some((l) => l.profile_version_id === t.profile_version_id);
              const cls = t.status === "succeeded" ? "ok" : t.status === "failed" ? "err" : t.status === "running" ? "info" : "warn";
              const label = t.status === "running" ? `${t.stage || "training"} ${Math.round((t.progress || 0) * 100)}%` : t.status;
              return (
                <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 12, fontSize: 13, flexWrap: "wrap" }}>
                  <span className="sub">Training status:</span>
                  <strong>{t.profile}</strong>
                  <span className={`pill ${cls}`}>{label}</span>
                  {t.status === "running" && t.eta_seconds != null && <span className="sub">~{Math.ceil(t.eta_seconds / 60)} min left</span>}
                  {t.status === "succeeded" && <span className="sub">{published ? "published as style model" : "done — ready to publish"}</span>}
                  {t.status === "failed" && t.error && <span className="sub" title={t.error}>{t.error}</span>}
                </div>
              );
            })()}
            {(trainings.data || []).some((t) => t.status === "queued" || t.status === "running") && (
              <div style={{ marginBottom: 14, display: "flex", flexDirection: "column", gap: 8 }}>
                {(trainings.data || [])
                  .filter((t) => t.status === "queued" || t.status === "running")
                  .map((t) => (
                    <div key={t.run_id} style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 13 }}>
                      <span style={{ minWidth: 160 }}>{t.profile}</span>
                      <div style={{ flex: 1, height: 8, background: "var(--border)", borderRadius: 4, overflow: "hidden" }}>
                        <div style={{ width: `${Math.round((t.progress || 0) * 100)}%`, height: "100%", background: "var(--accent)", transition: "width 0.5s" }} />
                      </div>
                      <span className="sub" style={{ minWidth: 150 }}>
                        {t.status === "queued" ? "queued" : `${t.stage || "training"} ${Math.round((t.progress || 0) * 100)}%`}
                        {t.eta_seconds != null ? ` · ~${Math.ceil(t.eta_seconds / 60)} min left` : ""}
                      </span>
                    </div>
                  ))}
              </div>
            )}
            {(trainings.data || []).some((t) => t.status === "succeeded" && t.profile_version_id && !(loras.data?.loras || []).some((l) => l.profile_version_id === t.profile_version_id)) && (
              <div style={{ marginBottom: 14, display: "flex", gap: 8, flexWrap: "wrap" }}>
                {(trainings.data || [])
                  .filter((t) => t.status === "succeeded" && t.profile_version_id && !(loras.data?.loras || []).some((l) => l.profile_version_id === t.profile_version_id))
                  .map((t) => (
                    <span key={t.run_id} style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                      <button className="btn" onClick={() => publishLora.mutate(t)}>
                        ⇈ Publish “{t.profile}” as style model
                      </button>
                      {(t.suggested_tags || []).length > 0 && (
                        <span className="sub" style={{ fontSize: 11 }}>auto-tags: {(t.suggested_tags || []).slice(0, 4).join(", ")}</span>
                      )}
                    </span>
                  ))}
              </div>
            )}
            <table className="table">
              <thead><tr><th>Name</th><th>Tags</th><th>State</th><th>Auto-apply</th><th>Priority</th><th>Scale</th><th /></tr></thead>
              <tbody>
                {(loras.data?.loras || []).map((l) => (
                  <tr key={l.id}>
                    <td>{l.name}<div className="mono" style={{ fontSize: 11 }}>{l.provenance}</div></td>
                    <td>
                      <input
                        style={{ width: 180 }}
                        defaultValue={l.tags.join(", ")}
                        onBlur={(e) => { if (e.target.value !== l.tags.join(", ")) patchLora.mutate({ id: l.id, body: { tags: e.target.value } }); }}
                      />
                    </td>
                    <td><button className="btn" onClick={() => patchLora.mutate({ id: l.id, body: { state: l.state === "active" ? "retired" : "active" } })}>{l.state}</button></td>
                    <td><button className="btn" onClick={() => patchLora.mutate({ id: l.id, body: { auto_apply: !l.auto_apply } })}>{l.auto_apply ? "on" : "off"}</button></td>
                    <td>{l.priority}</td>
                    <td>{l.default_scale.toFixed(2)}</td>
                    <td><button className="btn btn-ghost" onClick={() => deleteLora.mutate(l.id)}>✕</button></td>
                  </tr>
                ))}
                {loras.data && loras.data.loras.length === 0 && <tr><td colSpan={7} style={{ color: "var(--muted)" }}>No style models yet — upload a few songs to train one.</td></tr>}
              </tbody>
            </table>
          </div>
        )}

        {section === "jobs" && (
          <div className="card">
            <div className="card-header">
              <h2>Generation Jobs ({allJobs.data?.total ?? 0})</h2>
              <span className="spacer" />
              <select style={{ width: 140 }} value={jobTask} onChange={(e) => setJobTask(e.target.value)}>
                {TASK_OPTIONS.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
              </select>
              <select style={{ width: 140 }} value={jobStatus} onChange={(e) => setJobStatus(e.target.value)}>
                <option value="">All statuses</option>
                {["queued", "running", "succeeded", "failed", "cancelled"].map((x) => <option key={x} value={x}>{x}</option>)}
              </select>
            </div>
            {jobTable(allJobs.data?.items || [])}
            {(allJobs.data?.items.length ?? 0) < (allJobs.data?.total ?? 0) && (
              <div style={{ marginTop: 10 }}>
                <button className="btn" onClick={() => setJobLimit((n) => n + 25)}>Load more</button>
              </div>
            )}
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
                    <td><a className="link" href={`/admin/jobs?task=${sv.operation}`}>{sv.name}</a><div className="mono">{sv.kind} · {sv.version}</div></td>
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
            <div className="card-header">
              <h2>GPU Workers</h2>
              <span className="spacer" />
              <button className="btn" onClick={() => purge.mutate()}>Purge stale</button>
            </div>
            {(workers.data?.workers || []).map(workerRow)}
            {(workers.data?.workers || []).length === 0 && <p style={{ color: "var(--muted)" }}>No workers registered.</p>}
            {purge.data != null && <p style={{ color: "var(--muted)", fontSize: 12 }}>Last purge removed {purge.data.purged} worker(s).</p>}
          </div>
        )}

        {section === "vast" && (
          <div className="card">
            <div className="card-header">
              <h2>Vast Cloud</h2>
              <span className="spacer" />
              <span className="sub" style={{ fontSize: 12 }}>Recently used nodes are stopped (not destroyed) and restarted for the next job</span>
            </div>
            <table className="table">
              <thead><tr><th>Instance</th><th>Role</th><th>GPU</th><th>State</th><th>Vast status</th><th>Last used</th><th /></tr></thead>
              <tbody>
                {(vast.data?.instances || []).map((v) => (
                  <tr key={v.id}>
                    <td className="mono">{v.vast_instance_id}</td>
                    <td>{v.role}</td>
                    <td>{v.gpu_model || "—"}</td>
                    <td>
                      <span className={`pill ${v.state === "running" ? "ok" : v.state === "stopped" ? "warn" : ""}`}>{v.state}</span>
                    </td>
                    <td>{v.live_status ?? (vast.data?.live_available ? "—" : "not linked")}</td>
                    <td>{v.last_used_at ? new Date(v.last_used_at).toLocaleString() : "—"}</td>
                    <td style={{ display: "flex", gap: 6 }}>
                      {v.state === "stopped" && (
                        <button className="btn btn-sm" disabled={vastAction.isPending} onClick={() => vastAction.mutate({ id: v.vast_instance_id, action: "start" })}>Start</button>
                      )}
                      {v.state === "running" && (
                        <button className="btn btn-sm" disabled={vastAction.isPending} onClick={() => vastAction.mutate({ id: v.vast_instance_id, action: "stop" })}>Stop</button>
                      )}
                      <button className="btn btn-sm" disabled={vastAction.isPending} onClick={() => vastAction.mutate({ id: v.vast_instance_id, action: "destroy" })}>Destroy</button>
                    </td>
                  </tr>
                ))}
                {(vast.data?.instances || []).length === 0 && (
                  <tr><td colSpan={7} style={{ color: "var(--muted)" }}>No Vast instances tracked yet.</td></tr>
                )}
              </tbody>
            </table>
            {vastAction.error != null && <p className="form-error">{String((vastAction.error as Error).message)}</p>}
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
          <>
            <div className="card">
              <div className="card-header"><h2>Billing & Credits</h2></div>
              <div style={{ display: "flex", gap: 30, flexWrap: "wrap" }}>
                {[
                  ["Current Period Revenue", `$${billing.data.revenue.toLocaleString()}`],
                  ["Credits Used", `${billing.data.credits_used.toLocaleString()} / ${billing.data.credits_quota.toLocaleString()}`],
                  ["Credits Granted", billing.data.credits_granted.toLocaleString()],
                  ["Subscribers", String(billing.data.subscribers ?? 0)],
                ].map(([k, v]) => (
                  <div key={k}>
                    <div className="label" style={{ color: "var(--muted)", fontSize: 12 }}>{k}</div>
                    <div style={{ fontSize: 22, fontWeight: 800 }}>{v}</div>
                  </div>
                ))}
              </div>
              <div style={{ marginTop: 16, display: "grid", gap: 8, maxWidth: 460 }}>
                {[
                  ["API usage (generation)", billing.data.api_usage_pct],
                  ["Custom training", billing.data.custom_training_pct],
                  ["Audio export", billing.data.export_pct ?? 0],
                ].map(([label, pct]) => (
                  <div key={label as string} style={{ display: "flex", gap: 10, alignItems: "center", fontSize: 13 }}>
                    <span style={{ width: 170 }}>{label}</span>
                    <div style={{ flex: 1 }}><Progress value={(pct as number) / 100} /></div>
                    <span className="mono" style={{ width: 48, textAlign: "right" }}>{pct}%</span>
                  </div>
                ))}
              </div>
              <p style={{ color: "var(--muted)", fontSize: 12, marginTop: 14 }}>
                Revenue is the sum of active paid plans; job-activity splits come from real job counts.
              </p>
            </div>
            <div className="card" style={{ marginTop: 20 }}>
              <div className="card-header">
                <h2>Credit Ledger ({credits.data?.total ?? 0})</h2>
              </div>
              <table className="table">
                <thead><tr><th>When</th><th>User</th><th>Delta</th><th>Reason</th><th>Job</th></tr></thead>
                <tbody>
                  {(credits.data?.items || []).map((c) => (
                    <tr key={c.id}>
                      <td className="mono">{c.created_at?.slice(5, 16).replace("T", " ")}</td>
                      <td><Avatar name={c.user} sm /> {c.user}</td>
                      <td style={{ color: c.delta < 0 ? "#d43d3d" : "inherit" }}>{c.delta > 0 ? `+${c.delta}` : c.delta}</td>
                      <td>{c.reason}</td>
                      <td className="mono">{c.job_id ? <button className="link mono" style={{ border: 0, background: "none", cursor: "pointer", padding: 0, font: "inherit" }} onClick={() => setDetailId(c.job_id!)}>{c.job_id.slice(0, 8)}</button> : "—"}</td>
                    </tr>
                  ))}
                  {(credits.data?.items || []).length === 0 && <tr><td colSpan={5} style={{ color: "var(--muted)" }}>No credit entries yet.</td></tr>}
                </tbody>
              </table>
            </div>
          </>
        )}

        {section === "api" && (
          <div className="card">
            <div className="card-header"><h2>API Access</h2></div>
            <div style={{ display: "flex", gap: 8, marginBottom: 12 }}>
              <input style={{ width: 220 }} placeholder="new key name…" value={keyName} onChange={(e) => setKeyName(e.target.value)} />
              <button className="btn btn-primary" onClick={() => createKey.mutate()}>Create key</button>
            </div>
            {newSecret && (
              <p className="mono" style={{ fontSize: 12, padding: 8, border: "1px dashed var(--border)", marginBottom: 12 }}>
                {newSecret} — copy it now, it is shown only once.
              </p>
            )}
            <table className="table">
              <thead><tr><th>Name</th><th>Prefix</th><th>Created</th><th>Last used</th><th>Status</th><th /></tr></thead>
              <tbody>
                {(keys.data?.items || []).map((k) => (
                  <tr key={k.id}>
                    <td><strong>{k.name}</strong></td>
                    <td className="mono">{k.prefix}…</td>
                    <td className="mono">{k.created_at.slice(0, 10)}</td>
                    <td className="mono">{k.last_used_at ? k.last_used_at.slice(0, 16).replace("T", " ") : "never"}</td>
                    <td><StatusPill status={k.revoked_at ? "cancelled" : "online"} label={k.revoked_at ? "revoked" : "active"} /></td>
                    <td>{!k.revoked_at && <button className="btn" onClick={() => revokeKey.mutate(k.id)}>Revoke</button>}</td>
                  </tr>
                ))}
                {(keys.data?.items || []).length === 0 && <tr><td colSpan={6} style={{ color: "var(--muted)" }}>No API keys yet — create one to call the API with Authorization: Bearer …</td></tr>}
              </tbody>
            </table>
          </div>
        )}

        {section === "errors" && (
          <div className="card">
            <div className="card-header">
              <h2>Errors ({errors.data?.total ?? 0})</h2>
              <span className="spacer" />
              <span className="sub" style={{ fontSize: 12 }}>auto-purged after 30 days</span>
            </div>
            <table className="table">
              <thead><tr><th>When</th><th>Component</th><th>Code</th><th>Message</th><th>Links</th><th>State</th><th /></tr></thead>
              <tbody>
                {(errors.data?.items || []).map((e) => (
                  <tr key={e.id}>
                    <td className="mono">{e.created_at?.slice(5, 16).replace("T", " ")}</td>
                    <td>{e.component}</td>
                    <td><span className="pill err">{e.error_code}</span></td>
                    <td style={{ maxWidth: 320, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={e.message}>{e.message}</td>
                    <td className="mono" style={{ fontSize: 11 }}>{[e.job_id?.slice(0, 8), e.worker_id].filter(Boolean).join(" ") || "—"}</td>
                    <td>{e.resolved ? <span className="pill">resolved</span> : <span className="pill info">open</span>}</td>
                    <td style={{ display: "flex", gap: 6 }}>
                      <button className="btn" onClick={() => setErrorId(e.id)}>View</button>
                      <button className="btn" onClick={() => resolveError.mutate({ id: e.id, resolved: !e.resolved })}>
                        {e.resolved ? "Reopen" : "Resolve"}
                      </button>
                    </td>
                  </tr>
                ))}
                {(errors.data?.items || []).length === 0 && <tr><td colSpan={7} style={{ color: "var(--muted)" }}>No errors logged.</td></tr>}
              </tbody>
            </table>
            {(errors.data?.items.length ?? 0) < (errors.data?.total ?? 0) && (
              <div style={{ marginTop: 10 }}>
                <button className="btn" onClick={() => setErrorsLimit((n) => n + 20)}>View full log (+20)</button>
              </div>
            )}
            {errorId !== null && errorDetail.data && (
              <div className="card" style={{ marginTop: 14, background: "color-mix(in srgb, var(--surface) 70%, transparent)" }}>
                <div className="card-header">
                  <h3>#{errorDetail.data.id} — {errorDetail.data.error_code}</h3>
                  <span className="spacer" />
                  <button
                    className="btn"
                    onClick={() => navigator.clipboard?.writeText(errorDetail.data.agent_brief)}
                  >
                    Copy agent brief
                  </button>
                  <button className="btn btn-ghost" onClick={() => setErrorId(null)}>✕</button>
                </div>
                <pre className="mono" style={{ whiteSpace: "pre-wrap", fontSize: 12, maxHeight: 320, overflow: "auto" }}>
                  {errorDetail.data.agent_brief}
                </pre>
              </div>
            )}
          </div>
        )}

        {section === "pricing" && (
          <div className="card" style={{ maxWidth: 640 }}>
            <div className="card-header">
              <h2>Pricing</h2>
              <span className="spacer" />
              <button
                className="btn btn-primary"
                disabled={!pricingDraft || savePricing.isPending}
                onClick={() => pricingDraft && savePricing.mutate(pricingDraft)}
              >
                Save
              </button>
            </div>
            {(["plan", "pack"] as const).map((kind) => (
              <div key={kind}>
                <div className="label" style={{ color: "var(--muted)", fontSize: 12, margin: "10px 0 6px", textTransform: "capitalize" }}>{kind}s</div>
                <table className="table">
                  <thead><tr><th>Name</th><th>Price USD</th><th>Credits</th></tr></thead>
                  <tbody>
                    {(kind === "plan" ? pricing.data?.plan : pricing.data?.pack)?.map((row) => {
                      const draft = pricingDraft?.find((p) => p.id === row.id) || row;
                      const set = (patch: Partial<PricingRow>) =>
                        setPricingDraft((d) => (d || [...(pricing.data?.plan || []), ...(pricing.data?.pack || [])]).map((p) => (p.id === row.id ? { ...p, ...patch } : p)));
                      return (
                        <tr key={row.id}>
                          <td>{draft.name} <span className="mono" style={{ fontSize: 11 }}>({draft.id})</span></td>
                          <td>
                            <input style={{ width: 90 }} type="number" min={0} value={draft.price_usd} onChange={(e) => set({ price_usd: Number(e.target.value) })} />
                          </td>
                          <td>
                            <input style={{ width: 110 }} type="number" min={0} value={draft.credits} onChange={(e) => set({ credits: Number(e.target.value) })} />
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            ))}
            <p className="sub" style={{ fontSize: 12, marginTop: 8 }}>
              Plan credits are monthly grants; pack credits are one-time top-ups. Changes apply immediately.
            </p>
          </div>
        )}

        {section === "audit" && (
          <div className="card">
            <div className="card-header">
              <h2>Audit Log ({audit.data?.total ?? 0})</h2>
              <span className="spacer" />
              <input
                style={{ width: 160 }}
                placeholder="filter event…"
                value={auditEvent}
                onChange={(e) => setAuditEvent(e.target.value)}
              />
            </div>
            <table className="table">
              <thead><tr><th>Event</th><th>Job</th><th>Owner</th><th>Operation</th><th>When</th></tr></thead>
              <tbody>
                {(audit.data?.items || []).map((a, i) => (
                  <tr key={i}>
                    <td><StatusPill status={a.status} label={a.event} /></td>
                    <td className="mono"><button className="link mono" style={{ border: 0, background: "none", cursor: "pointer", padding: 0, font: "inherit" }} onClick={() => setDetailId(a.job_id)}>{a.job_id.slice(0, 8)}</button></td>
                    <td className="mono">{a.owner_id.replace(/^(tok|usr)_/, "").slice(0, 8)}</td>
                    <td>{a.operation}</td>
                    <td className="mono">{a.created_at?.slice(5, 16).replace("T", " ")}</td>
                  </tr>
                ))}
                {(audit.data?.items || []).length === 0 && <tr><td colSpan={5} style={{ color: "var(--muted)" }}>No events yet.</td></tr>}
              </tbody>
            </table>
            {(audit.data?.items.length ?? 0) < (audit.data?.total ?? 0) && (
              <div style={{ marginTop: 10 }}>
                <button className="btn" onClick={() => setAuditLimit((n) => n + 50)}>Load more</button>
              </div>
            )}
          </div>
        )}

        {section === "settings" && (
          <div className="card" style={{ maxWidth: 460 }}>
            <div className="card-header"><h2>Settings</h2></div>
            <div className="label" style={{ color: "var(--muted)", fontSize: 12, marginBottom: 6 }}>Site Template</div>
            <select value={site.data?.template || "open-canvas"} onChange={(e) => setTemplate.mutate(e.target.value)}>
              {TEMPLATES.map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
            <div className="label" style={{ color: "var(--muted)", fontSize: 12, margin: "14px 0 6px" }}>Environment</div>
            <select value={envValue} onChange={(e) => setEnvironment.mutate(e.target.value)}>
              {ENVIRONMENTS.map((e) => <option key={e} value={e}>{e}</option>)}
            </select>
            <p style={{ color: "var(--muted)", fontSize: 12, marginTop: 14 }}>
              Template and environment are stored as site settings and applied platform-wide.
            </p>
          </div>
        )}
      </div>

      {detailId && (
        <div className="drawer-overlay" onClick={() => setDetailId(null)}>
          <div className="drawer" onClick={(e) => e.stopPropagation()}>
            <div className="card-header">
              <h2>Job {detailId.slice(0, 8)}</h2>
              <span className="spacer" />
              <button className="btn" onClick={() => setDetailId(null)}>Close</button>
            </div>
            {!detail.data ? (
              <p style={{ color: "var(--muted)" }}>Loading…</p>
            ) : (
              <>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "6px 16px", fontSize: 13, marginBottom: 12 }}>
                  <span className="muted">User</span><span><Avatar name={detail.data.user} sm /> {detail.data.user}</span>
                  <span className="muted">Task</span><span>{detail.data.task}</span>
                  <span className="muted">Status</span><span><StatusPill status={detail.data.status} /></span>
                  <span className="muted">Stage</span><span>{detail.data.stage || "—"}</span>
                  <span className="muted">Progress</span><span>{detail.data.progress != null ? `${Math.round(detail.data.progress * 100)}%` : "—"}</span>
                  <span className="muted">Runtime</span><span>{fmtRuntime(detail.data.runtime_seconds)}</span>
                  <span className="muted">Created</span><span className="mono">{detail.data.created_at?.slice(0, 19).replace("T", " ")}</span>
                  {detail.data.error_code && <><span className="muted">Error</span><span className="mono">{detail.data.error_code}: {detail.data.error_message}</span></>}
                </div>
                {detail.data.progress != null && detail.data.status === "running" && <Progress value={detail.data.progress} />}
                <h3 style={{ margin: "14px 0 6px", fontSize: 14 }}>Events</h3>
                <table className="table">
                  <thead><tr><th>When</th><th>Event</th><th>Status</th><th>Stage</th></tr></thead>
                  <tbody>
                    {detail.data.events.map((ev, i) => (
                      <tr key={i}>
                        <td className="mono">{ev.created_at?.slice(5, 19).replace("T", " ")}</td>
                        <td>{ev.event}</td>
                        <td><StatusPill status={ev.status} /></td>
                        <td>{ev.stage || "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
