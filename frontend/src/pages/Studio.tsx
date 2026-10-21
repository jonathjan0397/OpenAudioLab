import { useEffect, useState } from "react";
import { Link, NavLink, useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, AuthUser } from "../api";
import CreateWidget, { DRAFT_KEY } from "../components/CreateWidget";
import ArtworkTile from "../components/ArtworkTile";
import Waveform from "../components/Waveform";
import { usePlayer } from "../components/PlayerContext";
import { useWorkspace } from "../components/WorkspaceContext";
import { Donut, Progress, StatusPill, fmtTime, humanizeStage } from "../components/ui";
import { exportArtifact } from "../components/social";
import { buildGenerationRequest } from "../lib/generation";

interface Track {
  asset_id: string;
  role?: string;
  title: string | null;
  slug?: string | null;
  shared: boolean;
  favorite: boolean;
  duration_seconds: number | null;
  created_at: string | null;
  expired: boolean;
  url: string;
  job_id?: string | null;
  seed?: number | null;
  workspace_id?: string | null;
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
  is_default: boolean;
  song_count: number;
  asset_count: number;
  artist_profile_id?: string | null;
  artist?: {
    profile_id: string;
    name: string;
    applicable: boolean;
    default_adapter_id: string | null;
    adapter_model_selection: string | null;
    adapter_state: string | null;
    is_main?: boolean;
  } | null;
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
  is_main: boolean;
  default_voice_profile_id: string | null;
}

const SIDEBAR = [
  { to: "/studio", label: "My Studio", icon: "⌂" },
  { to: "/", label: "Create Music", icon: "✦" },
  { to: "/artists", label: "Artist Profiles", icon: "☺" },
  { to: "/training", label: "Training", icon: "◈" },
  { to: "/voice", label: "Voice Studio", icon: "◉" },
  { to: "/settings", label: "Settings", icon: "⚙" },
];

function tokenOf(url: string): string | undefined {
  return url.split("token=")[1];
}

// Turn a raw generation manifest into labelled rows for the Details card.
const CONTROL_LABELS: Record<string, string> = {
  bpm: "BPM", key_scale: "Key", time_signature: "Time signature", vocal_language: "Language",
  mood: "Mood", gender: "Vocal", inference_steps: "Steps", guidance_scale: "Guidance",
  shift: "Shift", use_adg: "Adaptive guidance",
};
function formatDetails(m: Record<string, any> | undefined): [string, string][] {
  if (!m) return [];
  const r = m.requested || {}, e = m.effective || {}, c = r.controls || {};
  const s = (v: unknown) => (v == null || v === "" ? undefined : String(v));
  const rows: ([string, string | undefined] | undefined)[] = [
    ["Model", s(r.model_selection || r.model_id)],
    ["Profile", s(r.execution_profile_id)],
    ["Engine", s(r.engine_model || e.engine_version)],
    r.planner_model ? ["Planner", s(r.planner_model)] : undefined,
    r.model_revision ? ["Revision", s(r.model_revision)] : undefined,
    ["Task", s(r.task_type || "text2music")],
    r.duration_seconds != null ? ["Duration", `${r.duration_seconds} s`] : undefined,
    r.instrumental != null ? ["Instrumental", r.instrumental ? "yes" : "no"] : undefined,
    e.seed != null || r.seed != null ? ["Seed", s(e.seed ?? r.seed)] : undefined,
    r.lyrics_sha256 ? ["Lyrics", `${s(r.lyrics_origin) || "provided"} · ${r.lyrics_sha256.slice(0, 10)}`] : undefined,
    ["Description", s(r.music_description)],
    s(r.song_idea) ? ["Song idea", s(r.song_idea)] : undefined,
    s(r.style_prompt) ? ["Style", s(r.style_prompt)] : undefined,
    ...Object.entries(c).map(([k, v]) => [CONTROL_LABELS[k] || k, s(v)] as [string, string | undefined]),
    s(r.src_asset_id) ? ["Source track", s(r.src_asset_id!.slice(0, 8)) + "…"] : undefined,
    s(r.reference_asset_id) ? ["Reference", s(r.reference_asset_id!.slice(0, 8)) + "…"] : undefined,
    r.audio_cover_strength != null ? ["Cover strength", s(r.audio_cover_strength)] : undefined,
    r.cover_noise_strength != null ? ["Cover noise", s(r.cover_noise_strength)] : undefined,
    r.repaint_mode ? ["Repaint", `${s(r.repaint_mode)}${r.repaint_strength != null ? ` @ ${r.repaint_strength}` : ""}`] : undefined,
    s(r.lora_id) ? ["LoRA", s(r.lora_id!.slice(0, 8)) + "…"] : undefined,
    m.created_at ? ["Created", String(m.created_at).slice(0, 19).replace("T", " ")] : undefined,
  ];
  return rows.filter((x): x is [string, string] => !!x && !!x[1] && x[1] !== "");
}

export default function StudioPage() {
  const qc = useQueryClient();
  const player = usePlayer();
  const navigate = useNavigate();
  const me = useQuery({
    queryKey: ["me"],
    queryFn: () => api.get<{ user: AuthUser; allowance?: { plan: string; monthly_credits: number } }>("/api/v1/auth/me"),
    retry: false,
  });
  const stats = useQuery({
    queryKey: ["track-stats"],
    queryFn: () => api.get<{ total: number; shared: number; favorites: number }>("/api/v1/tracks/stats"),
    enabled: !!me.data?.user,
  });
  const { activeId } = useWorkspace();
  const [wsFilter, setWsFilter] = useState<string>("all");
  useEffect(() => {
    if (activeId) setWsFilter(activeId);
  }, [activeId]);
  const tracks = useQuery({
    queryKey: ["my-tracks", wsFilter],
    queryFn: () => api.get<{ tracks: Track[] }>(`/api/v1/tracks?limit=50${wsFilter !== "all" ? `&workspace_id=${encodeURIComponent(wsFilter)}` : ""}`),
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
  const [repaintFor, setRepaintFor] = useState<string | null>(null);
  const [repaintStart, setRepaintStart] = useState("0");
  const [repaintEnd, setRepaintEnd] = useState("8");
  const [repaintCaption, setRepaintCaption] = useState("");
  const [newArtistName, setNewArtistName] = useState("");
  const [wsActive, setWsActive] = useState<string | null>(null);
  const [wsNewName, setWsNewName] = useState("");
  const [wsRenaming, setWsRenaming] = useState<string | null>(null);
  const [wsRenameValue, setWsRenameValue] = useState("");
  const [showIndivStems, setShowIndivStems] = useState(false);
  const [copiedRaw, setCopiedRaw] = useState(false);
  const stemsQuery = useQuery<{ asset_id: string; stems: { category: string | null; asset_id: string; url: string }[]; zip: { asset_id: string | null; url: string; bytes?: number } | null }>({
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
      setWsFilter("all");
      qc.invalidateQueries({ queryKey: ["workspaces"] });
      qc.invalidateQueries({ queryKey: ["my-tracks"] });
    },
  });
  const wsMove = useMutation({
    mutationFn: ({ assetIds, workspaceId }: { assetIds: string[]; workspaceId: string | null }) =>
      api.post("/api/v1/workspaces/move", { asset_ids: assetIds, workspace_id: workspaceId }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["my-tracks"] });
      qc.invalidateQueries({ queryKey: ["workspaces"] });
    },
  });
  const wsRename = useMutation({
    mutationFn: ({ id, name }: { id: string; name: string }) => api.patch(`/api/v1/workspaces/${id}`, { name }),
    onSuccess: () => {
      setWsRenaming(null);
      qc.invalidateQueries({ queryKey: ["workspaces"] });
    },
  });
  const wsAttach = useMutation({
    mutationFn: ({ id, profileId }: { id: string; profileId: string | null }) =>
      api.patch(`/api/v1/workspaces/${id}/artist`, { artist_profile_id: profileId }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["workspaces"] });
      qc.invalidateQueries({ queryKey: ["workspaces-active"] });
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
          ...(activeId || s.workspace_id ? { workspace_id: activeId || s.workspace_id } : {}),
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
          workspaceId: activeId || t.workspace_id || undefined,
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

  const repaintFromTrack = useMutation({
    mutationFn: (t: Track) =>
      api.post<{ job_id: string }>(
        "/api/v1/jobs",
        buildGenerationRequest({
          idea: "",
          styles: repaintCaption.trim(),
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
          title: `${t.title || "Untitled"} · Repaint`,
          lyrics: "",
          lyricsProvided: true,
          instrumental: true,
          durationSeconds: Math.max(10, Math.min(120, Math.round(t.duration_seconds || 15))),
          loraId: "",
          taskType: "repaint",
          workspaceId: activeId || t.workspace_id || undefined,
          srcAssetId: t.asset_id,
          repaintingStart: Math.max(0, Number(repaintStart) || 0),
          repaintingEnd: Math.max(0, Number(repaintEnd) || 0),
          repaintMode: "balanced",
          repaintStrength: 0.6,
          chunkMaskMode: "auto",
        }),
        { "Idempotency-Key": crypto.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}` },
      ),
    onSuccess: () => {
      setRepaintFor(null);
      setRepaintCaption("");
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
  const allowance = me.data?.allowance?.monthly_credits ?? 0;

  return (
    <div className="dash">
      <aside className="dash-sidebar">
        {SIDEBAR.map((s, i) => (
          <NavLink key={i} to={s.to} end={s.to === "/"}>
            <span aria-hidden>{s.icon}</span> {s.label}
          </NavLink>
        ))}
        <div className="side-note">
          <strong>{balance.toLocaleString()}</strong> credits remaining
          <div style={{ marginTop: 6 }}>
            <Progress value={allowance > 0 ? balance / allowance : null} />
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
              <div className="value">{(stats.data?.total ?? all.length).toLocaleString()}</div>
            </div>
          </div>
          <div className="card stat-card">
            <span className="icon">◎</span>
            <div style={{ flex: 1 }}>
              <div className="label">Credits Remaining</div>
              <div className="value">{balance.toLocaleString()}</div>
              <div className="sub">{allowance > 0 ? `of ${allowance.toLocaleString()} monthly` : "purchased balance"}</div>
            </div>
            <span className="chart">
              <Donut value={allowance > 0 ? balance / allowance : 0} size={58}
                     label={allowance > 0 ? `${Math.round((balance / allowance) * 100)}%` : "—"} />
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
              <div className="value">{(stats.data?.shared ?? all.filter((t) => t.shared).length).toLocaleString()}</div>
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
              <div style={{ display: "flex", gap: 6, flexWrap: "wrap", margin: "6px 0 4px" }}>
                <button type="button" className={`chip${wsFilter === "all" ? " chip-picked" : ""}`} onClick={() => setWsFilter("all")}>All spaces</button>
                {(workspaces.data?.workspaces || []).map((w) => (
                  <button
                    key={w.workspace_id}
                    type="button"
                    className={`chip${wsFilter === w.workspace_id ? " chip-picked" : ""}`}
                    onClick={() => setWsFilter(wsFilter === w.workspace_id ? "all" : w.workspace_id)}
                  >
                    {w.name} ({w.asset_count})
                  </button>
                ))}
              </div>
              {shown.length === 0 && <p style={{ color: "var(--muted)" }}>No tracks here yet — generate one above or pick another space.</p>}
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
                    <a className="btn" href={`${t.url}${t.url.includes("?") ? "&" : "?"}download=1`} download>WAV</a>
                    <button className="btn" onClick={() => exportArtifact(t.asset_id, "mp3")}>MP3</button>
                    {(workspaces.data?.workspaces || []).length > 0 && (() => {
                      const ws = workspaces.data!.workspaces;
                      const defId = (ws.find((w) => w.is_default) || ws[0]).workspace_id;
                      const current = t.workspace_id || defId;
                      return (
                        <select
                          className="btn"
                          title="Move this track to a workspace"
                          value={current}
                          style={{ fontSize: 12 }}
                          onChange={(ev) => wsMove.mutate({ assetIds: [t.asset_id], workspaceId: ev.target.value === defId ? null : ev.target.value })}
                        >
                          {ws.map((w) => <option key={w.workspace_id} value={w.workspace_id}>{`♪ ${w.name}`}</option>)}
                        </select>
                      );
                    })()}
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
                      <button
                        className="btn"
                        style={repaintFor === t.asset_id ? { borderColor: "var(--accent)", color: "var(--accent)" } : undefined}
                        onClick={() => {
                          setRepaintFor(repaintFor === t.asset_id ? null : t.asset_id);
                          setRepaintStart("0");
                          setRepaintEnd(String(Math.max(2, Math.round((t.duration_seconds || 15) / 2))));
                          setRepaintCaption("");
                        }}
                      >
                        ✦ Repaint
                      </button>
                    </div>
                  </div>
                  {repaintFor === t.asset_id && (
                    <div className="card" style={{ padding: "10px 14px", margin: "-6px 0 10px", background: "color-mix(in srgb, var(--surface) 70%, transparent)" }}>
                      <div className="sub" style={{ fontSize: 12, marginBottom: 6 }}>
                        Re-generate a time region (seconds) of this take; audio outside the region is preserved. Bounds within 0–{Math.round(t.duration_seconds || 15)}s.
                      </div>
                      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
                        <input type="number" min={0} max={Math.round(t.duration_seconds || 15)} value={repaintStart} onChange={(e) => setRepaintStart(e.target.value)} style={{ width: 64 }} aria-label="Repaint start seconds" />
                        <span className="sub">→</span>
                        <input type="number" min={0} max={Math.round(t.duration_seconds || 15)} value={repaintEnd} onChange={(e) => setRepaintEnd(e.target.value)} style={{ width: 64 }} aria-label="Repaint end seconds" />
                        <input value={repaintCaption} onChange={(e) => setRepaintCaption(e.target.value)} placeholder="what should play in this region" maxLength={200} style={{ flex: 1, minWidth: 160 }} />
                        <button
                          className="btn btn-primary"
                          disabled={!(Number(repaintEnd) > Number(repaintStart)) || repaintFromTrack.isPending}
                          onClick={() => repaintFromTrack.mutate(t)}
                        >
                          {repaintFromTrack.isPending ? "Repainting…" : "✦ Repaint region"}
                        </button>
                      </div>
                      <div className="sub" style={{ fontSize: 11, marginTop: 6, opacity: 0.8 }}>
                        Note: true lengthening/continuation is a separate capability; this repaints within the existing clip.
                      </div>
                      {repaintFromTrack.isError && (
                        <div style={{ color: "var(--danger, #e57373)", fontSize: 12, marginTop: 6 }}>
                          {(repaintFromTrack.error as Error)?.message || "Repaint failed."}
                        </div>
                      )}
                    </div>
                  )}
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
                   <div className="card" style={{ padding: "10px 14px", margin: "-6px 0 10px", background: "color-mix(in srgb, var(--surface) 70%, transparent)", minWidth: 0 }}>
                     {(stemsQuery.isLoading || stemsQuery.isFetching) && <span style={{ color: "var(--muted)", fontSize: 12 }}>Loading stems…</span>}
                     {stemsQuery.data && stemsQuery.data.stems.length === 0 && (
                       <span style={{ display: "inline-flex", gap: 10, alignItems: "center", fontSize: 12, color: "var(--muted)" }}>
                         No stems yet.
                         <button className="btn" onClick={() => exportArtifact(t.asset_id, "stems")}>Separate now (Demucs)</button>
                       </span>
                     )}
                     {stemsQuery.data && stemsQuery.data.stems.length > 0 && (
                       <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center", fontSize: 12, minWidth: 0 }}>
                         {stemsQuery.data.zip && (
                           <a className="btn btn-primary" href={stemsQuery.data.zip.url} download style={{ fontSize: 12 }}>↓ All stems (.zip)</a>
                         )}
                         <button className="btn btn-ghost" style={{ fontSize: 12 }} onClick={() => setShowIndivStems((v) => !v)}>
                           {showIndivStems ? "hide individual" : "show individual"}
                         </button>
                         {showIndivStems && stemsQuery.data.stems.map((s) => (
                           <a key={s.asset_id} className="btn" href={s.url} download style={{ fontSize: 12 }}>↓ {s.category}</a>
                         ))}
                       </div>
                     )}
                   </div>
                 )}
                 {detailsFor === t.asset_id && (
                   <div className="card" style={{ padding: "10px 14px", margin: "-6px 0 10px", background: "color-mix(in srgb, var(--surface) 70%, transparent)", minWidth: 0 }}>
                     {(manifestQuery.isLoading || manifestQuery.isFetching) && <span style={{ color: "var(--muted)", fontSize: 12 }}>Loading generation details…</span>}
                     {manifestQuery.data && (
                       <div style={{ minWidth: 0 }}>
                         <dl style={{ display: "grid", gridTemplateColumns: "max-content 1fr", gap: "4px 14px", margin: "0 0 10px", fontSize: 12 }}>
                           {formatDetails(manifestQuery.data.manifest).map(([k, v]) => (
                             <div key={k} style={{ display: "contents" }}>
                               <dt style={{ color: "var(--muted)", whiteSpace: "nowrap" }}>{k}</dt>
                               <dd style={{ margin: 0, color: "var(--text, inherit)", overflowWrap: "anywhere" }}>{v}</dd>
                             </div>
                           ))}
                         </dl>
                         <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                           <button className="btn" onClick={() => reuseFromManifest(manifestQuery.data.manifest)}>Reuse recipe</button>
                           <button className="btn btn-ghost" onClick={() => {
                             navigator.clipboard?.writeText(JSON.stringify(manifestQuery.data.manifest, null, 2)).then(() => {
                               setCopiedRaw(true); setTimeout(() => setCopiedRaw(false), 1500);
                             });
                           }}>{copiedRaw ? "Copied ✓" : "Copy raw"}</button>
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
                {(workspaces.data?.workspaces || []).map((w) =>
                  wsRenaming === w.workspace_id ? (
                    <span key={w.workspace_id} style={{ display: "inline-flex", gap: 6, alignItems: "center" }}>
                      <input value={wsRenameValue} onChange={(e) => setWsRenameValue(e.target.value)} maxLength={80} style={{ width: 160 }} />
                      <button className="btn" disabled={!wsRenameValue.trim()} onClick={() => wsRename.mutate({ id: w.workspace_id, name: wsRenameValue.trim() })}>Save</button>
                      <button className="btn btn-ghost" onClick={() => setWsRenaming(null)}>Cancel</button>
                    </span>
                  ) : (
                    <span key={w.workspace_id} style={{ display: "inline-flex", gap: 4, alignItems: "center" }}>
                      <button
                        type="button"
                        className={`chip${wsActive === w.workspace_id ? " chip-picked" : ""}`}
                        onClick={() => setWsActive(wsActive === w.workspace_id ? null : w.workspace_id)}
                      >
                        {w.name} ({w.asset_count}{w.song_count ? ` · ${w.song_count} saved` : ""}){w.is_default ? " ★" : ""}
                      </button>
                      {!w.is_default && (
                        <>
                          <button className="btn btn-ghost" title="Rename" onClick={() => { setWsRenaming(w.workspace_id); setWsRenameValue(w.name); }}>✎</button>
                          <button className="btn btn-ghost" title="Delete (tracks return to My Default Space)" onClick={() => { if (window.confirm(`Delete "${w.name}"? Its tracks move to My Default Space.`)) wsDelete.mutate(w.workspace_id); }}>🗑</button>
                        </>
                      )}
                    </span>
                  )
                )}
              </div>
              {wsActive && (
                <div style={{ marginTop: 10 }}>
                  {(() => {
                    const cur = (workspaces.data?.workspaces || []).find((w) => w.workspace_id === wsActive);
                    const profileList = artists.data || [];
                    if (!cur) return null;
                    return (
                      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10, flexWrap: "wrap" }}>
                        <span className="sub" style={{ fontSize: 12 }}>Artist for this space:</span>
                        {profileList.length > 0 ? (
                          <select
                            value={cur.artist_profile_id || ""}
                            disabled={wsAttach.isPending}
                            onChange={(e) => wsAttach.mutate({ id: cur.workspace_id, profileId: e.target.value || null })}
                          >
                            <option value="">— none (no voice/style) —</option>
                            {profileList.map((a) => (
                              <option key={a.profile_id} value={a.profile_id}>
                                {`${a.is_main ? "★ " : ""}${a.name}${a.default_voice_profile_id ? "" : "  (no voice profile)"}`}
                              </option>
                            ))}
                          </select>
                        ) : (
                          <span className="sub" style={{ fontSize: 12 }}>Train an artist profile first, then attach it here.</span>
                        )}
                        {cur.artist?.applicable && <span className="pill ok">♪ voice adapter applied to new songs</span>}
                        {cur.artist && !cur.artist.applicable && <span className="pill warn">needs a validated voice adapter</span>}
                      </div>
                    );
                  })()}
                  {(wsSongs.data?.songs || []).length === 0 && (
                    <p style={{ color: "var(--muted)", fontSize: 13 }}>No saved recipes here yet — use the “♪ space” move control on a track, or “+ Add” above.</p>
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
                    {humanizeStage(j.stage) || "Queued"}
                    {j.progress != null ? ` · ${Math.round(j.progress * 100)}%` : ""}
                  </div>
                  <Progress value={j.progress ?? null} />
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
