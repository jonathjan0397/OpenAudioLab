import { useState } from "react";
import { Link, NavLink, useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, AuthUser } from "../api";
import CreateWidget, { DRAFT_KEY } from "../components/CreateWidget";
import ArtworkTile from "../components/ArtworkTile";
import Waveform from "../components/Waveform";
import { usePlayer } from "../components/PlayerContext";
import { Donut, Progress, StatusPill, fmtTime } from "../components/ui";
import { exportArtifact } from "../components/social";
import { buildGenerationRequest } from "../lib/generation";

interface Track {
  asset_id: string;
  role?: string;
  title: string | null;
  shared: boolean;
  favorite: boolean;
  duration_seconds: number | null;
  created_at: string | null;
  expired: boolean;
  url: string;
  job_id?: string | null;
  seed?: number | null;
}
interface JobRow {
  job_id: string;
  status: string;
  stage?: string | null;
  progress?: number | null;
  created_at?: string | null;
}
interface Workspace {
  workspace_id: string;
  name: string;
  song_count: number;
}
interface WorkspaceSong {
  song_id: string;
  workspace_id: string;
  title: string | null;
  description: string | null;
  lyrics: string | null;
  style_tags: string[];
  seed: number | null;
  duration_seconds: number | null;
  instrumental: boolean;
  asset_id: string | null;
  job_id: string | null;
}
interface ArtistRow {
  profile_id: string;
  name: string;
  slug: string | null;
  bio: string | null;
  sharing_policy: string;
  etag: string;
}

const SIDEBAR = [
  { to: "/studio", label: "Dashboard", icon: "⌂" },
  { to: "/", label: "Create Music", icon: "✦" },
  { to: "/studio", label: "My Tracks", icon: "♪" },
  { to: "/artists", label: "Artist Profiles", icon: "☺" },
  { to: "/training", label: "Training", icon: "◈" },
  { to: "/settings", label: "Settings", icon: "⚙" },
];

function tokenOf(url: string): string | undefined {
  return url.split("token=")[1];
}

export default function StudioPage() {
  const qc = useQueryClient();
  const player = usePlayer();
  const navigate = useNavigate();
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
  const [stemsFor, setStemsFor] = useState<string | null>(null);
  const [detailsFor, setDetailsFor] = useState<string | null>(null);
  const [remixFor, setRemixFor] = useState<string | null>(null);
  const [remixStyle, setRemixStyle] = useState("");
  const [newArtistName, setNewArtistName] = useState("");
  const [wsActive, setWsActive] = useState<string | null>(null);
  const [wsNewName, setWsNewName] = useState("");
  const stemsQuery = useQuery<{ asset_id: string; stems: { category: string | null; asset_id: string; url: string }[] }>({
    queryKey: ["stems", stemsFor],
    queryFn: () => api.get(`/api/v1/artifacts/${stemsFor}/stems`),
    enabled: !!stemsFor,
  });
  const manifestQuery = useQuery<{ asset_id: string; manifest: Record<string, any> }>({
    queryKey: ["generation-manifest", detailsFor],
    queryFn: () => api.get(`/api/v1/artifacts/${detailsFor}/manifest`),
    enabled: !!detailsFor,
  });
  const workspaces = useQuery({
    queryKey: ["workspaces"],
    queryFn: () => api.get<{ workspaces: Workspace[] }>("/api/v1/workspaces"),
    enabled: !!me.data?.user,
  });
  const wsSongs = useQuery({
    queryKey: ["workspace-songs", wsActive],
    queryFn: () => api.get<{ songs: WorkspaceSong[] }>(`/api/v1/workspaces/${wsActive}/songs`),
    enabled: !!wsActive,
  });
  const artists = useQuery({
    queryKey: ["artist-profiles"],
    queryFn: () => api.get<ArtistRow[]>("/api/v1/artist-profiles"),
    enabled: !!me.data?.user,
  });

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
  const wsCreate = useMutation({
    mutationFn: (name: string) => api.post<{ workspace_id: string }>("/api/v1/workspaces", { name }),
    onSuccess: () => {
      setWsNewName("");
      qc.invalidateQueries({ queryKey: ["workspaces"] });
    },
  });
  const wsDelete = useMutation({
    mutationFn: (id: string) => api.delete(`/api/v1/workspaces/${id}`),
    onSuccess: () => {
      setWsActive(null);
      qc.invalidateQueries({ queryKey: ["workspaces"] });
    },
  });
  const wsSave = useMutation({
    mutationFn: ({ wsId, jobId, title }: { wsId: string; jobId: string; title: string }) =>
      api.post(`/api/v1/workspaces/${wsId}/songs`, { job_id: jobId, title }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["workspaces"] });
      qc.invalidateQueries({ queryKey: ["workspace-songs"] });
    },
  });
  const wsRemove = useMutation({
    mutationFn: ({ wsId, songId }: { wsId: string; songId: string }) =>
      api.delete(`/api/v1/workspaces/${wsId}/songs/${songId}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["workspace-songs"] });
      qc.invalidateQueries({ queryKey: ["workspaces"] });
    },
  });
  const artistPatch = useMutation({
    mutationFn: ({ id, etag, body }: { id: string; etag: string; body: Record<string, unknown> }) =>
      api.patch(`/api/v1/artist-profiles/${id}`, body, { "If-Match": etag }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["artist-profiles"] }),
  });

  const artistCreate = useMutation({
    mutationFn: (name: string) => api.post("/api/v1/artist-profiles", { name }),
    onSuccess: () => {
      setNewArtistName("");
      qc.invalidateQueries({ queryKey: ["artist-profiles"] });
    },
  });

  const reuseFromManifest = (m: Record<string, any> | undefined) => {
    if (!m) return;
    const req = m.requested || {};
    const res = m.resolved || {};
    const controls = req.controls || {};
    localStorage.setItem(
      DRAFT_KEY,
      JSON.stringify({
        title: req.title || "",
        desc: req.song_idea || controls.description || req.music_description || "",
        styles: req.style_prompt || controls.styles || "",
        lyrics: res.lyrics || "",
        mood: controls.mood || "",
        instrumental: !!req.instrumental,
        gender: controls.gender || "",
        loraId: req.lora_id || "",
        bpm: controls.bpm || "",
        keyScale: controls.key_scale || "",
        timeSignature: controls.time_signature || "",
        language: controls.vocal_language || "",
        shift: controls.shift ?? 1,
        quality: controls.inference_steps ?? 8,
        variations: controls.variations ?? 1,
        duration: req.duration_seconds ?? 120,
        drafted: !!res.lyrics,
        draftOpen: true,
      })
    );
    navigate("/");
  };

  const rerollSong = (s: WorkspaceSong, sameSeed: boolean) => {
    const parts = [s.description || "", ...(s.style_tags || [])].filter(Boolean);
    api
      .post<{ job_id: string }>(
        "/api/v1/jobs",
        {
          operation: "music.generate",
          model_id: "ace-step-1.5",
          music_description: parts.join(", ") || s.title || "Untitled",
          ...(s.description ? { song_idea: s.description } : {}),
          ...(s.style_tags && s.style_tags.length ? { style_prompt: s.style_tags.join(", ") } : {}),
          ...(s.lyrics && !s.instrumental ? { lyrics: s.lyrics, lyrics_origin: "human" } : {}),
          seed: sameSeed ? s.seed ?? Math.floor(Math.random() * 1_000_000_000) : Math.floor(Math.random() * 1_000_000_000),
          ...(s.duration_seconds ? { duration_seconds: s.duration_seconds } : {}),
          instrumental: !!s.instrumental,
          outputs: ["mix_wav"],
        },
        { "Idempotency-Key": crypto.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}` }
      )
      .then(() => {
        qc.invalidateQueries({ queryKey: ["my-jobs"] });
        qc.invalidateQueries({ queryKey: ["my-tracks"] });
      });
  };

  const coverFromTrack = useMutation({
    mutationFn: (t: Track) =>
      api.post<{ job_id: string }>(
        "/api/v1/jobs",
        buildGenerationRequest({
          idea: "",
          styles: remixStyle.trim(),
          mood: "",
          gender: "",
          bpm: "",
          keyScale: "",
          timeSignature: "",
          language: "",
          shift: 1,
          quality: 8,
          guidance: 0,
          variations: 1,
          title: `${t.title || "Untitled"} · Cover`,
          lyrics: "",
          lyricsProvided: true,
          instrumental: true,
          durationSeconds: Math.max(10, Math.min(120, Math.round(t.duration_seconds || 30))),
          loraId: "",
          taskType: "cover",
          srcAssetId: t.asset_id,
          audioCoverStrength: 0.7,
        }),
        { "Idempotency-Key": crypto.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}` },
      ),
    onSuccess: () => {
      setRemixFor(null);
      setRemixStyle("");
      qc.invalidateQueries({ queryKey: ["my-jobs"] });
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
              <div className="sub">of 5,000</div>
            </div>
            <span className="chart">
              <Donut value={balance / 5000} size={58} label={`${Math.round((balance / 5000) * 100)}%`} />
            </span>
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
                <>
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
                    {t.role && t.role !== "mix_wav" ? (
                      <span className="pill muted">{t.role === "mix_mp3" ? "MP3 export" : t.role}</span>
                    ) : (
                    <Waveform
                      assetId={t.asset_id}
                      token={tokenOf(t.url)}
                      progress={player.current?.asset_id === t.asset_id ? player.progress : 0}
                      onSeek={(r) => {
                        player.play({ asset_id: t.asset_id, title: t.title || "Untitled", url: t.url, duration: t.duration_seconds });
                        setTimeout(() => player.seek(r), 60);
                      }}
                    />
                    )}
                  </div>
                  <div className="actions">
                    <StatusPill status={t.expired ? "failed" : "completed"} label={t.expired ? "expired" : "ready"} />
                    <button className={`heart${t.favorite ? " on" : ""}`} onClick={() => toggle.mutate(t.asset_id)}>
                      {t.favorite ? "♥" : "♡"}
                    </button>
                    <button className="btn" onClick={() => share.mutate({ id: t.asset_id, shared: !t.shared })}>
                      {t.shared ? "Shared" : "Share"}
                    </button>
                    <a className="btn" href={t.url} download>WAV</a>
                    <button className="btn" onClick={() => exportArtifact(t.asset_id, "mp3")}>MP3</button>
                    {t.job_id && (workspaces.data?.workspaces || []).length > 0 && (
                      <button
                        className="btn"
                        title="Save recipe to workspace"
                        onClick={() => {
                          const wsId = wsActive && (workspaces.data?.workspaces || []).some((w) => w.workspace_id === wsActive)
                            ? wsActive
                            : workspaces.data!.workspaces[0].workspace_id;
                          wsSave.mutate({ wsId, jobId: t.job_id!, title: t.title || "Untitled" });
                        }}
                      >
                        + Workspace
                      </button>
                    )}
                    <button
                      className="btn"
                      style={stemsFor === t.asset_id ? { borderColor: "var(--accent)", color: "var(--accent)" } : undefined}
                      onClick={() => {
                        setStemsFor(stemsFor === t.asset_id ? null : t.asset_id);
                        qc.invalidateQueries({ queryKey: ["stems", t.asset_id] });
                      }}
                    >
                      ≋ Stems
                    </button>
                    <button
                      className="btn"
                      style={detailsFor === t.asset_id ? { borderColor: "var(--accent)", color: "var(--accent)" } : undefined}
                      onClick={() => {
                        setDetailsFor(detailsFor === t.asset_id ? null : t.asset_id);
                        qc.invalidateQueries({ queryKey: ["generation-manifest", t.asset_id] });
                      }}
                     >
                       ⓘ Details
                     </button>
                     <button
                       className="btn"
                       style={remixFor === t.asset_id ? { borderColor: "var(--accent)", color: "var(--accent)" } : undefined}
                       onClick={() => {
                         setRemixFor(remixFor === t.asset_id ? null : t.asset_id);
                         setRemixStyle("");
                       }}
                     >
                       ✦ Remix
                     </button>
                   </div>
                 </div>
                 {remixFor === t.asset_id && (
                   <div className="card" style={{ padding: "10px 14px", margin: "-6px 0 10px", background: "color-mix(in srgb, var(--surface) 70%, transparent)" }}>
                     <div className="sub" style={{ fontSize: 12, marginBottom: 6 }}>
                       Cover this take with a new style. The engine restyles from this exact source audio (approximate preservation — melody/arrangement may shift).
                     </div>
                     <div style={{ display: "flex", gap: 8 }}>
                       <input
                         value={remixStyle}
                         onChange={(e) => setRemixStyle(e.target.value)}
                         placeholder="e.g. thrash metal, fast and aggressive"
                         maxLength={200}
                         style={{ flex: 1 }}
                       />
                       <button
                         className="btn btn-primary"
                         disabled={!remixStyle.trim() || coverFromTrack.isPending}
                         onClick={() => coverFromTrack.mutate(t)}
                       >
                         {coverFromTrack.isPending ? "Covering…" : "✦ Cover it"}
                       </button>
                     </div>
                     {coverFromTrack.isError && t.asset_id === remixFor && (
                       <div style={{ color: "var(--danger, #e57373)", fontSize: 12, marginTop: 6 }}>
                         {(coverFromTrack.error as Error)?.message || "Cover failed."}
                       </div>
                     )}
                     {coverFromTrack.isSuccess && !coverFromTrack.isPending && (
                       <div className="sub" style={{ color: "var(--accent)", fontSize: 12, marginTop: 6 }}>Cover queued — see the Live queue below.</div>
                     )}
                   </div>
                 )}
                 {stemsFor === t.asset_id && (
                  <div className="card" style={{ padding: "10px 14px", margin: "-6px 0 10px", background: "color-mix(in srgb, var(--surface) 70%, transparent)" }}>
                    {(stemsQuery.isLoading || stemsQuery.isFetching) && <span style={{ color: "var(--muted)", fontSize: 12 }}>Loading stems…</span>}
                    {stemsQuery.data && stemsQuery.data.stems.length === 0 && (
                      <span style={{ display: "inline-flex", gap: 10, alignItems: "center", fontSize: 12, color: "var(--muted)" }}>
                        No stems yet.
                        <button className="btn" onClick={() => exportArtifact(t.asset_id, "stems")}>Separate now (Demucs)</button>
                      </span>
                    )}
                    {stemsQuery.data && stemsQuery.data.stems.length > 0 && (
                      <span style={{ display: "flex", gap: 10, flexWrap: "wrap", fontSize: 12 }}>
                        {stemsQuery.data.stems.map((s) => (
                          <a key={s.asset_id} className="btn" href={s.url} download style={{ fontSize: 12 }}>
                            ↓ {s.category}
                          </a>
                        ))}
                      </span>
                    )}
                  </div>
                )}
                {detailsFor === t.asset_id && (
                  <div className="card" style={{ padding: "10px 14px", margin: "-6px 0 10px", background: "color-mix(in srgb, var(--surface) 70%, transparent)" }}>
                    {(manifestQuery.isLoading || manifestQuery.isFetching) && <span style={{ color: "var(--muted)", fontSize: 12 }}>Loading generation details…</span>}
                    {manifestQuery.data && (
                      <div style={{ display: "grid", gap: 8, fontSize: 12 }}>
                        <div className="sub">
                          seed {manifestQuery.data.manifest?.effective?.seed ?? "unknown"} ·
                          engine {manifestQuery.data.manifest?.effective?.engine_version ?? "unknown"} ·
                          lyrics {manifestQuery.data.manifest?.requested?.lyrics_sha256?.slice(0, 12) ?? "none"}
                        </div>
                        <pre className="mono" style={{ margin: 0, whiteSpace: "pre-wrap", color: "var(--muted)" }}>
                          {JSON.stringify(manifestQuery.data.manifest?.requested?.controls || {}, null, 2)}
                        </pre>
                        <div>
                          <button className="btn" onClick={() => reuseFromManifest(manifestQuery.data.manifest)}>Reuse recipe</button>
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </>
              ))}
            </div>

            <div className="card" style={{ marginTop: 20 }}>
              <div className="card-header">
                <h2>Workspaces</h2>
                <span className="spacer" />
                <input
                  value={wsNewName}
                  onChange={(e) => setWsNewName(e.target.value)}
                  placeholder="New workspace name"
                  maxLength={80}
                  style={{ width: 180 }}
                />
                <button className="btn" disabled={!wsNewName.trim() || wsCreate.isPending} onClick={() => wsCreate.mutate(wsNewName.trim())}>
                  + Add
                </button>
              </div>
              {(workspaces.data?.workspaces || []).length === 0 && (
                <p style={{ color: "var(--muted)", fontSize: 13 }}>No workspaces yet — create one and save tracks into it.</p>
              )}
              <div className="style-chips">
                {(workspaces.data?.workspaces || []).map((w) => (
                  <button
                    key={w.workspace_id}
                    type="button"
                    className={`chip${wsActive === w.workspace_id ? " chip-picked" : ""}`}
                    onClick={() => setWsActive(wsActive === w.workspace_id ? null : w.workspace_id)}
                  >
                    {w.name} ({w.song_count})
                  </button>
                ))}
              </div>
              {wsActive && (
                <div style={{ marginTop: 10 }}>
                  {(wsSongs.data?.songs || []).length === 0 && (
                    <p style={{ color: "var(--muted)", fontSize: 13 }}>Empty — use “+ Workspace” on any track below.</p>
                  )}
                  {(wsSongs.data?.songs || []).map((s) => (
                    <div key={s.song_id} style={{ display: "flex", alignItems: "center", gap: 10, padding: "6px 0", borderBottom: "1px solid color-mix(in srgb, var(--border) 40%, transparent)" }}>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div className="title" style={{ fontSize: 14 }}>{s.title || "Untitled"}</div>
                        <div className="sub" style={{ fontSize: 12 }}>
                          seed {s.seed ?? "—"}{s.duration_seconds ? ` · ${fmtTime(s.duration_seconds)}` : ""}{s.instrumental ? " · instrumental" : ""}
                        </div>
                      </div>
                      <button className="btn" title="Regenerate with the same seed (reproducible)" onClick={() => rerollSong(s, true)}>↻ Replay</button>
                      <button className="btn" title="Regenerate with a new seed" onClick={() => rerollSong(s, false)}>✦ Reroll</button>
                      <button className="btn" onClick={() => wsRemove.mutate({ wsId: wsActive, songId: s.song_id })}>✕</button>
                    </div>
                  ))}
                  <div style={{ marginTop: 8 }}>
                    <button className="btn btn-ghost" onClick={() => wsDelete.mutate(wsActive)}>Delete workspace</button>
                  </div>
                </div>
              )}
            </div>

            <div className="card" style={{ marginTop: 20 }}>
              <div className="card-header">
                <h3>My Artists</h3>
                <span className="spacer" />
                <input
                  value={newArtistName}
                  onChange={(e) => setNewArtistName(e.target.value)}
                  placeholder="New artist name"
                  maxLength={80}
                  style={{ width: 160 }}
                />
                <button className="btn" disabled={!newArtistName.trim() || artistCreate.isPending} onClick={() => artistCreate.mutate(newArtistName.trim())}>
                  + Add
                </button>
                <NavLink to="/artists" className="btn">Browse all</NavLink>
              </div>
              {(artists.data || []).length === 0 && (
                <p style={{ color: "var(--muted)", fontSize: 13 }}>No artist profiles yet.</p>
              )}
              {(artists.data || []).map((a) => (
                <div key={a.profile_id} style={{ display: "flex", alignItems: "center", gap: 10, padding: "6px 0" }}>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div className="title" style={{ fontSize: 14 }}>{a.name}</div>
                    <div className="sub" style={{ fontSize: 12 }}>
                      {a.slug ? <Link className="link" to={`/artists/${a.slug}`}>/{a.slug}</Link> : "no slug"} · {a.sharing_policy}{a.bio ? ` · ${a.bio.slice(0, 40)}` : ""}
                    </div>
                  </div>
                  <button
                    className="btn"
                    onClick={() =>
                      artistPatch.mutate({
                        id: a.profile_id,
                        etag: a.etag,
                        body: { sharing: a.sharing_policy === "public" ? "private" : "public" },
                      })
                    }
                  >
                    {a.sharing_policy === "public" ? "Make private" : "Make public"}
                  </button>
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
