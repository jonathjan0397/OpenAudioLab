import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import { api } from "../api";
import ArtworkTile from "./ArtworkTile";
import Waveform from "./Waveform";
import { usePlayer } from "./PlayerContext";
import { exportArtifact } from "./social";
import { fmtTime } from "./ui";

interface JobAccepted {
  job_id: string;
}
interface JobDetail {
  status: string;
  stage?: string | null;
  progress?: number | null;
  error_code?: string | null;
  error_message?: string | null;
}
interface ArtifactItem {
  asset_id: string;
  role: string;
  mime: string;
  duration_seconds: number | null;
  title?: string | null;
}
interface DownloadResp {
  url: string;
}
interface LoraList {
  loras: { id: string; name: string; kind: string }[];
}
interface SuggestResp {
  tags: { tag: string; source: string }[];
}

const DURATIONS = [
  { value: 30, label: "~30 seconds" },
  { value: 60, label: "~1 minute" },
  { value: 120, label: "~2 minutes" },
  { value: 180, label: "~3 minutes" },
  { value: 240, label: "~4 minutes" },
];

const MOODS = ["Hopeful", "Melancholic", "Energetic", "Calm", "Dreamy", "Dark"];

const KEYS = [
  "C Major", "G Major", "D Major", "A Major", "E Major", "F Major", "Bb Major",
  "Am", "Em", "Bm", "F#m", "Dm", "Cm", "Gm",
];

const LANGUAGES = [
  { value: "en", label: "English" },
  { value: "es", label: "Spanish" },
  { value: "fr", label: "French" },
  { value: "de", label: "German" },
  { value: "pt", label: "Portuguese" },
  { value: "it", label: "Italian" },
  { value: "ja", label: "Japanese" },
  { value: "ko", label: "Korean" },
  { value: "zh", label: "Chinese" },
  { value: "hi", label: "Hindi" },
];

const QUALITY = [
  { value: 8, label: "Turbo (fast)" },
  { value: 16, label: "Balanced" },
  { value: 32, label: "Fine (slow)" },
];

export default function CreateWidget({
  variant = "card",
  showStyle = false,
  mode = "create",
}: {
  variant?: "card" | "wide" | "panel";
  showStyle?: boolean;
  mode?: "create" | "remix" | "extend";
}) {
  const player = usePlayer();
  const [easy, setEasy] = useState(() => localStorage.getItem("oal-create-mode") !== "advanced");
  const [desc, setDesc] = useState("A dreamy indie pop song about chasing a brighter tomorrow");
  const [style, setStyle] = useState("");
  const [lyrics, setLyrics] = useState("");
  const [drafted, setDrafted] = useState(false);
  const [duration, setDuration] = useState(60);
  const [instrumental, setInstrumental] = useState(false);
  const [mood, setMood] = useState("Hopeful");
  const [gender, setGender] = useState("");
  const [loraId, setLoraId] = useState("");
  const [bpm, setBpm] = useState("");
  const [keyScale, setKeyScale] = useState("");
  const [language, setLanguage] = useState("");
  const [shift, setShift] = useState(1);
  const [quality, setQuality] = useState(8);
  const [variations, setVariations] = useState(1);
  const [chipSeed, setChipSeed] = useState(() => Math.floor(Math.random() * 1e9));
  const [jobId, setJobId] = useState<string | null>(null);
  const [error, setError] = useState("");

  const loras = useQuery({
    queryKey: ["loras"],
    queryFn: () => api.get<LoraList>("/api/v1/loras"),
    staleTime: 300000,
  });

  const chips = useQuery({
    queryKey: ["style-chips", chipSeed],
    queryFn: () => api.get<SuggestResp>(`/api/v1/styles/suggest?limit=4&seed=${chipSeed}`),
    staleTime: 600000,
  });

  const draft = useMutation({
    mutationFn: () =>
      api.post<{ lyrics: string; style: string }>("/api/v1/llm/draft", {
        prompt: desc,
        lora_tags: (loras.data?.loras || []).flatMap((l) => [l.name.toLowerCase()]),
      }),
    onSuccess: (d) => {
      setLyrics(d.lyrics);
      setStyle(d.style);
      setDrafted(true);
      setError("");
    },
    onError: (e: Error) => setError(e.message),
  });

  const generate = useMutation({
    mutationFn: async () => {
      let finalLyrics = lyrics.trim() || undefined;
      if (!instrumental && !finalLyrics) {
        const r = await api.post<{ text: string }>("/api/v1/llm/lyrics", { prompt: desc, mode: "write" });
        finalLyrics = r.text;
      }
      const controls: Record<string, unknown> = { mood: mood.toLowerCase() };
      if (!instrumental && gender) controls.gender = gender;
      if (bpm) controls.bpm = Number(bpm);
      if (keyScale) controls.key_scale = keyScale;
      if (language) controls.vocal_language = language;
      if (shift !== 1) controls.shift = shift;
      if (quality !== 8) controls.inference_steps = quality;
      if (variations > 1) controls.variations = variations;
      const parts = [desc, mood ? `${mood.toLowerCase()} mood` : "", style].filter(Boolean);
      return api.post<JobAccepted>(
        "/api/v1/jobs",
        {
          operation: "music.generate",
          model_id: "ace-step-1.5",
          music_description: parts.join(", "),
          ...(finalLyrics && !instrumental ? { lyrics: finalLyrics, lyrics_origin: "frontend_llm" } : {}),
          controls,
          duration_seconds: mode === "extend" ? Math.min(duration + 60, 600) : duration,
          ...(mode === "remix" ? { seed: Math.floor(Math.random() * 1_000_000_000) } : {}),
          instrumental,
          ...(loraId ? { lora_id: loraId } : {}),
          outputs: ["mix_wav"],
        },
        { "Idempotency-Key": crypto.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}` }
      );
    },
    onSuccess: (d) => {
      setError("");
      setJobId(d.job_id);
    },
    onError: (e: Error) => setError(e.message),
  });

  const job = useQuery({
    queryKey: ["job", jobId],
    queryFn: () => api.get<JobDetail>(`/api/v1/jobs/${jobId}`),
    enabled: !!jobId,
    refetchInterval: (q) =>
      q.state.data?.status === "succeeded" || q.state.data?.status === "failed" ? false : 2000,
  });

  const artifacts = useQuery({
    queryKey: ["job-artifacts", jobId],
    queryFn: () => api.get<{ artifacts: ArtifactItem[] }>(`/api/v1/jobs/${jobId}/artifacts`),
    enabled: job.data?.status === "succeeded",
  });

  const urls = useQuery({
    queryKey: ["job-urls", jobId],
    queryFn: async () => {
      const list = artifacts.data?.artifacts.filter((a) => a.mime.startsWith("audio/")) || [];
      const out: Record<string, string> = {};
      for (const a of list) {
        out[a.asset_id] = (await api.post<DownloadResp>(`/api/v1/artifacts/${a.asset_id}/download-url`)).url;
      }
      return out;
    },
    enabled: !!artifacts.data,
  });

  const status = job.data?.status;
  const busy = generate.isPending || draft.isPending || (status ? status !== "succeeded" && status !== "failed" : false);
  const actionLabel = mode === "remix" ? "✦ Remix" : mode === "extend" ? "✦ Extend" : "✦ Generate";
  const results = (artifacts.data?.artifacts || []).filter((a) => a.mime.startsWith("audio/"));

  const addChip = (tag: string) => {
    setStyle((s) => {
      const clean = s.replace(/\s*,?\s*$/, "");
      return clean ? `${clean}, ${tag}` : tag;
    });
  };

  const toggleMode = () => {
    const next = !easy;
    setEasy(next);
    localStorage.setItem("oal-create-mode", next ? "easy" : "advanced");
  };

  return (
    <div className={`card create-panel create-${variant}`}>
      <div className="create-mode-row">
        <div className="segmented">
          <button type="button" className={easy ? "active" : ""} onClick={() => { setEasy(true); localStorage.setItem("oal-create-mode", "easy"); }}>Easy</button>
          <button type="button" className={!easy ? "active" : ""} onClick={toggleMode}>Advanced</button>
        </div>
        <span className="sub" style={{ fontSize: 12, color: "var(--muted)" }}>
          {easy ? "Describe a vibe — AI drafts lyrics & style for review" : "Full control over every generation parameter"}
        </span>
      </div>
      <div className="create-input-row">
        <span className="input-spark" aria-hidden>✦</span>
        <textarea
          rows={variant === "wide" ? 1 : variant === "panel" ? 4 : 3}
          maxLength={500}
          value={desc}
          onChange={(e) => setDesc(e.target.value)}
          placeholder={easy ? "Enter a vibe or idea… e.g. rainy lo-fi study night" : "Describe the music you want…"}
        />
        {variant !== "wide" && <span className="char-count">{desc.length}/500</span>}
        {variant === "wide" && (
          <button className="btn btn-primary btn-lg gen-wide" disabled={!!busy} onClick={() => generate.mutate()}>
            {busy ? "✦ Generating…" : actionLabel} →
          </button>
        )}
      </div>
      {easy && (
        <div className="create-draft-row">
          <button className="btn" disabled={draft.isPending || !desc.trim()} onClick={() => draft.mutate()}>
            {draft.isPending ? "✦ Writing…" : drafted ? "✦ Rewrite with AI" : "✦ Write with AI"}
          </button>
          {drafted && <span className="pill" style={{ fontSize: 11 }}>Review before generating</span>}
        </div>
      )}
      {easy && drafted && (
        <div className="create-review">
          <div className="field">
            <label>Style tags</label>
            <input value={style} onChange={(e) => setStyle(e.target.value)} placeholder="lofi, chill, female vocals" />
          </div>
          {!instrumental && (
            <div className="field">
              <label>Lyrics</label>
              <textarea rows={5} value={lyrics} onChange={(e) => setLyrics(e.target.value)} placeholder="[Verse]…" />
            </div>
          )}
        </div>
      )}
      <div className="style-chips">
        {(chips.data?.tags || []).map((c) => (
          <button
            key={c.tag}
            type="button"
            className={`chip${c.source === "lora" ? " chip-lora" : ""}`}
            title={c.source === "lora" ? "Trained style model" : c.source === "trending" ? "Trending tag" : "Suggested tag"}
            onClick={() => addChip(c.tag)}
          >
            + {c.tag}
          </button>
        ))}
        <button type="button" className="chip chip-shuffle" title="Shuffle tags" onClick={() => setChipSeed(Math.floor(Math.random() * 1e9))}>♻</button>
        <Link to="/styles" className="chip chip-link">cheat sheet ↗</Link>
      </div>
      <div className="create-controls">
        {showStyle && (
          <div className="field ctrl">
            <span className="ctrl-icon" aria-hidden>♪</span>
            <div className="field">
              <label>Style model</label>
              <select value={loraId} onChange={(e) => setLoraId(e.target.value)}>
                <option value="">Auto (match tags)</option>
                {(loras.data?.loras || []).map((l) => (
                  <option key={l.id} value={l.id}>
                    {l.name}
                  </option>
                ))}
              </select>
            </div>
          </div>
        )}
        <div className="field ctrl">
          <span className="ctrl-icon" aria-hidden>☺</span>
          <div className="field">
            <label>Mood</label>
            <select value={mood} onChange={(e) => setMood(e.target.value)}>
              {MOODS.map((m) => (
                <option key={m} value={m}>{m}</option>
              ))}
            </select>
          </div>
        </div>
        <div className="field ctrl">
          <span className="ctrl-icon" aria-hidden>⇍</span>
          <div className="field">
            <label>Instrumental / Vocal</label>
            <div className="segmented">
              <button type="button" className={!instrumental ? "active" : ""} onClick={() => setInstrumental(false)}>
                Vocal
              </button>
              <button type="button" className={instrumental ? "active" : ""} onClick={() => setInstrumental(true)}>
                Instrumental
              </button>
            </div>
          </div>
        </div>
        {!instrumental && (
          <div className="field ctrl">
            <span className="ctrl-icon" aria-hidden>🎤</span>
            <div className="field">
              <label>Lead singer</label>
              <div className="segmented">
                <button type="button" className={gender === "" ? "active" : ""} onClick={() => setGender("")}>Any</button>
                <button type="button" className={gender === "male" ? "active" : ""} onClick={() => setGender("male")}>Male</button>
                <button type="button" className={gender === "female" ? "active" : ""} onClick={() => setGender("female")}>Female</button>
              </div>
            </div>
          </div>
        )}
        <div className="field ctrl">
          <span className="ctrl-icon" aria-hidden>◷</span>
          <div className="field">
            <label>Duration</label>
            <select value={duration} onChange={(e) => setDuration(Number(e.target.value))}>
              {DURATIONS.map((d) => (
                <option key={d.value} value={d.value}>
                  {d.label}
                </option>
              ))}
            </select>
          </div>
        </div>
        {variant !== "wide" && (
          <button className="btn btn-primary btn-lg" disabled={!!busy} onClick={() => generate.mutate()}>
            {busy ? "✦ Generating…" : actionLabel} →
          </button>
        )}
      </div>
      {!easy && (
        <div className="create-advanced">
          <div className="field ctrl">
            <div className="field">
              <label>BPM</label>
              <input type="number" min={30} max={300} value={bpm} onChange={(e) => setBpm(e.target.value)} placeholder="Auto" />
            </div>
          </div>
          <div className="field ctrl">
            <div className="field">
              <label>Key</label>
              <select value={keyScale} onChange={(e) => setKeyScale(e.target.value)}>
                <option value="">Auto</option>
                {KEYS.map((k) => <option key={k} value={k}>{k}</option>)}
              </select>
            </div>
          </div>
          <div className="field ctrl">
            <div className="field">
              <label>Vocal language</label>
              <select value={language} onChange={(e) => setLanguage(e.target.value)}>
                <option value="">Auto</option>
                {LANGUAGES.map((l) => <option key={l.value} value={l.value}>{l.label}</option>)}
              </select>
            </div>
          </div>
          <div className="field ctrl">
            <div className="field">
              <label>Weirdness {shift.toFixed(2)}</label>
              <input type="range" min={0.5} max={2} step={0.05} value={shift} onChange={(e) => setShift(Number(e.target.value))} />
            </div>
          </div>
          <div className="field ctrl">
            <div className="field">
              <label>Quality</label>
              <select value={quality} onChange={(e) => setQuality(Number(e.target.value))}>
                {QUALITY.map((q) => <option key={q.value} value={q.value}>{q.label}</option>)}
              </select>
            </div>
          </div>
          <div className="field ctrl">
            <div className="field">
              <label>Variations (2× credits)</label>
              <div className="segmented">
                <button type="button" className={variations === 1 ? "active" : ""} onClick={() => setVariations(1)}>1</button>
                <button type="button" className={variations === 2 ? "active" : ""} onClick={() => setVariations(2)}>2</button>
              </div>
            </div>
          </div>
        </div>
      )}
      {error && <p className="pill err" style={{ marginTop: 12 }}>{error}</p>}
      {status === "failed" && (
        <p className="pill err" style={{ marginTop: 12 }}>
          {job.data?.error_code}: {job.data?.error_message}
        </p>
      )}
      {busy && (
        <div style={{ marginTop: 14 }}>
          <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, color: "var(--muted)", marginBottom: 5 }}>
            <span>{job.data?.stage ? `${job.data.stage}…` : "Queued…"}</span>
            <span>{job.data?.progress != null ? `${Math.round(job.data.progress * 100)}%` : ""}</span>
          </div>
          <div className="progress">
            <i style={{ width: `${Math.round((job.data?.progress ?? 0.08) * 100)}%` }} />
          </div>
        </div>
      )}
      {results.map((result) => {
        const resultUrl = urls.data?.[result.asset_id];
        if (!resultUrl) return null;
        return (
          <div className="track-row" key={result.asset_id} style={{ marginTop: 14, borderBottom: 0 }}>
            <ArtworkTile
              seed={result.asset_id}
              size={64}
              onPlay={() =>
                player.play({
                  asset_id: result.asset_id,
                  title: result.title || "New track",
                  url: resultUrl,
                  duration: result.duration_seconds,
                  subtitle: "Just generated",
                })
              }
            />
            <div className="meta">
              <div className="title">{result.title || "New track"}</div>
              <div className="sub">
                {fmtTime(result.duration_seconds)} · {instrumental ? "Instrumental" : "Vocal"}
              </div>
            </div>
            <div className="wave">
              <Waveform
                assetId={result.asset_id}
                token={resultUrl.split("token=")[1]}
                progress={player.current?.asset_id === result.asset_id ? player.progress : 0}
                onSeek={(r) => {
                  player.play({ asset_id: result.asset_id, title: result.title || "New track", url: resultUrl, duration: result.duration_seconds });
                  setTimeout(() => player.seek(r), 60);
                }}
              />
            </div>
            <div className="actions">
              <a className="btn" href={resultUrl} download>↓ WAV</a>
              <button className="btn" onClick={() => exportArtifact(result.asset_id, "mp3")}>♫ MP3</button>
              <button className="btn" onClick={() => exportArtifact(result.asset_id, "stems")}>≋ Stems</button>
            </div>
          </div>
        );
      })}
    </div>
  );
}
