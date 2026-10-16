import { useState } from "react";
import { NavLink } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, AuthUser } from "../api";
import CreateWidget from "../components/CreateWidget";
import ArtworkTile from "../components/ArtworkTile";
import Waveform from "../components/Waveform";
import { usePlayer } from "../components/PlayerContext";
import { Progress, StatusPill, fmtTime } from "../components/ui";

interface Track {
  asset_id: string;
  title: string | null;
  shared: boolean;
  favorite: boolean;
  duration_seconds: number | null;
  created_at: string | null;
  expired: boolean;
  url: string;
}
interface JobRow {
  job_id: string;
  status: string;
  stage?: string | null;
  progress?: number | null;
  created_at?: string | null;
}

const SIDEBAR = [
  { to: "/studio", label: "Dashboard", icon: "⌂" },
  { to: "/", label: "Create Music", icon: "✦" },
  { to: "/studio", label: "My Tracks", icon: "♪" },
  { to: "/artists", label: "Artist Profiles", icon: "☺" },
  { to: "/studio", label: "Training", icon: "◈" },
  { to: "/studio", label: "Settings", icon: "⚙" },
];

function tokenOf(url: string): string | undefined {
  return url.split("token=")[1];
}

export default function StudioPage() {
  const qc = useQueryClient();
  const player = usePlayer();
  const me = useQuery({
    queryKey: ["me"],
    queryFn: () => api.get<{ user: AuthUser }>("/api/v1/auth/me"),
    retry: false,
  });
  const tracks = useQuery({
    queryKey: ["my-tracks"],
    queryFn: () => api.get<{ tracks: Track[] }>("/api/v1/tracks?limit=50"),
    enabled: !!me.data?.user,
  });
  const credits = useQuery({
    queryKey: ["credits"],
    queryFn: () => api.get<{ balance: number | null }>("/api/v1/credits"),
    enabled: !!me.data?.user,
  });
  const jobs = useQuery({
    queryKey: ["my-jobs"],
    queryFn: () => api.get<{ jobs: JobRow[] }>("/api/v1/jobs?limit=20"),
    enabled: !!me.data?.user,
    refetchInterval: 4000,
  });
  const [renaming, setRenaming] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [filter, setFilter] = useState("all");

  const toggle = useMutation({
    mutationFn: (id: string) => api.post(`/api/v1/artifacts/${id}/favorite`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["my-tracks"] }),
  });
  const share = useMutation({
    mutationFn: ({ id, shared }: { id: string; shared: boolean }) =>
      api.patch(`/api/v1/artifacts/${id}`, { shared }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["my-tracks"] }),
  });
  const rename = useMutation({
    mutationFn: ({ id, title }: { id: string; title: string }) =>
      api.patch(`/api/v1/artifacts/${id}`, { title }),
    onSuccess: () => {
      setRenaming(null);
      qc.invalidateQueries({ queryKey: ["my-tracks"] });
    },
  });

  if (!me.data?.user) {
    return (
      <main className="page">
        <h1>My Studio</h1>
        <p style={{ color: "var(--muted)" }}>Sign in (top right) to see your studio.</p>
      </main>
    );
  }

  const all = tracks.data?.tracks || [];
  const shown = filter === "favorites" ? all.filter((t) => t.favorite) : filter === "shared" ? all.filter((t) => t.shared) : all;
  const active = (jobs.data?.jobs || []).filter((j) =>
    ["queued", "waiting_for_worker", "running"].includes(j.status)
  );
  const balance = credits.data?.balance ?? 0;

  return (
    <div className="dash">
      <aside className="dash-sidebar">
        {SIDEBAR.map((s, i) => (
          <NavLink key={i} to={s.to} className={i === 0 ? "active" : ""}>
            <span aria-hidden>{s.icon}</span> {s.label}
          </NavLink>
        ))}
        <div className="side-note">
          <strong>{balance.toLocaleString()}</strong> credits remaining
          <div style={{ marginTop: 6 }}>
            <Progress value={balance / 5000} />
          </div>
        </div>
      </aside>
      <div className="dash-main">
        <div className="hero-strip">
          <h1>My Studio</h1>
          <div className="sub">Welcome back, {me.data.user.username} 👋 — turn ideas into music.</div>
        </div>

        <div className="stat-grid">
          <div className="card stat-card">
            <span className="icon">♪</span>
            <div>
              <div className="label">Tracks Created</div>
              <div className="value">{all.length}</div>
            </div>
          </div>
          <div className="card stat-card">
            <span className="icon">◎</span>
            <div style={{ flex: 1 }}>
              <div className="label">Credits Remaining</div>
              <div className="value">{balance.toLocaleString()}</div>
              <div style={{ marginTop: 6 }}>
                <Progress value={balance / 5000} />
              </div>
            </div>
          </div>
          <div className="card stat-card">
            <span className="icon">⇍</span>
            <div>
              <div className="label">Active Jobs</div>
              <div className="value">{active.length}</div>
              <div className="sub">{active.length ? "generation in progress" : "all caught up"}</div>
            </div>
          </div>
          <div className="card stat-card">
            <span className="icon">☺</span>
            <div>
              <div className="label">Shared Tracks</div>
              <div className="value">{all.filter((t) => t.shared).length}</div>
              <div className="sub">visible in Trending</div>
            </div>
          </div>
        </div>

        <div className="main-cols" style={{ marginTop: 22 }}>
          <div style={{ minWidth: 0 }}>
            <CreateWidget variant="panel" showStyle />
            <div className="card" style={{ marginTop: 20 }}>
              <div className="card-header">
                <h2>My Tracks</h2>
                <span className="spacer" />
                <div className="segmented">
                  <button type="button" className={filter === "all" ? "active" : ""} onClick={() => setFilter("all")}>All</button>
                  <button type="button" className={filter === "favorites" ? "active" : ""} onClick={() => setFilter("favorites")}>Favorites</button>
                  <button type="button" className={filter === "shared" ? "active" : ""} onClick={() => setFilter("shared")}>Shared</button>
                </div>
              </div>
              {shown.length === 0 && <p style={{ color: "var(--muted)" }}>No tracks yet — generate one above.</p>}
              {shown.map((t) => (
                <div className="track-row" key={t.asset_id}>
                  <ArtworkTile
                    seed={t.asset_id}
                    size={56}
                    onPlay={() =>
                      player.play({
                        asset_id: t.asset_id,
                        title: t.title || "Untitled",
                        url: t.url,
                        duration: t.duration_seconds,
                        subtitle: me.data.user?.username,
                      })
                    }
                  />
                  <div className="meta">
                    {renaming === t.asset_id ? (
                      <span style={{ display: "flex", gap: 6 }}>
                        <input value={renameValue} onChange={(e) => setRenameValue(e.target.value)} autoFocus />
                        <button className="btn btn-primary" onClick={() => rename.mutate({ id: t.asset_id, title: renameValue })}>OK</button>
                      </span>
                    ) : (
                      <div
                        className="title"
                        style={{ cursor: "pointer" }}
                        title="Click to rename"
                        onClick={() => {
                          setRenaming(t.asset_id);
                          setRenameValue(t.title || "");
                        }}
                      >
                        {t.title || "Untitled (click to name)"}
                      </div>
                    )}
                    <div className="sub">
                      {fmtTime(t.duration_seconds)} · {t.created_at?.slice(0, 10)}
                    </div>
                  </div>
                  <div className="wave">
                    <Waveform
                      assetId={t.asset_id}
                      token={tokenOf(t.url)}
                      progress={player.current?.asset_id === t.asset_id ? player.progress : 0}
                      onSeek={(r) => {
                        player.play({ asset_id: t.asset_id, title: t.title || "Untitled", url: t.url, duration: t.duration_seconds });
                        setTimeout(() => player.seek(r), 60);
                      }}
                    />
                  </div>
                  <div className="actions">
                    <button className={`heart${t.favorite ? " on" : ""}`} onClick={() => toggle.mutate(t.asset_id)}>
                      {t.favorite ? "♥" : "♡"}
                    </button>
                    <button className="btn" onClick={() => share.mutate({ id: t.asset_id, shared: !t.shared })}>
                      {t.shared ? "Shared" : "Share"}
                    </button>
                    <a className="btn" href={t.url} download>WAV</a>
                  </div>
                </div>
              ))}
            </div>
          </div>

          <aside style={{ display: "grid", gap: 18, alignContent: "start" }}>
            <div className="card">
              <div className="card-header">
                <h3>Generation Queue</h3>
                <span className="spacer" />
                <span className="pill info">{active.length} active</span>
              </div>
              {active.length === 0 && <p style={{ color: "var(--muted)", fontSize: 13 }}>Nothing running.</p>}
              {active.map((j) => (
                <div key={j.job_id} style={{ marginBottom: 14 }}>
                  <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13, marginBottom: 4 }}>
                    <span className="mono">{j.job_id.slice(0, 8)}</span>
                    <StatusPill status={j.status} />
                  </div>
                  <div style={{ fontSize: 12, color: "var(--muted)", marginBottom: 4 }}>
                    {j.stage ? `${j.stage}…` : "queued…"}
                  </div>
                  <Progress value={j.progress ?? 0.06} />
                </div>
              ))}
            </div>
            <div className="card">
              <div className="card-header">
                <h3>Recent</h3>
              </div>
              {(jobs.data?.jobs || []).slice(0, 5).map((j) => (
                <div key={j.job_id} style={{ display: "flex", justifyContent: "space-between", gap: 8, padding: "6px 0", fontSize: 13 }}>
                  <span className="mono">{j.job_id.slice(0, 8)}</span>
                  <StatusPill status={j.status} />
                </div>
              ))}
            </div>
          </aside>
        </div>
      </div>
    </div>
  );
}
