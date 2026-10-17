import { useState } from "react";
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

const DURATIONS = [
  { value: 30, label: "~30 seconds" },
  { value: 60, label: "~1 minute" },
  { value: 120, label: "~2 minutes" },
  { value: 180, label: "~3 minutes" },
  { value: 240, label: "~4 minutes" },
];

const MOODS = ["Hopeful", "Melancholic", "Energetic", "Calm", "Dreamy", "Dark"];

export default function CreateWidget({
  variant = "card",
  showStyle = false,
}: {
  variant?: "card" | "wide" | "panel";
  showStyle?: boolean;
}) {
  const player = usePlayer();
  const [desc, setDesc] = useState("A dreamy indie pop song about chasing a brighter tomorrow");
  const [duration, setDuration] = useState(60);
  const [instrumental, setInstrumental] = useState(false);
  const [mood, setMood] = useState("Hopeful");
  const [loraId, setLoraId] = useState("");
  const [jobId, setJobId] = useState<string | null>(null);
  const [error, setError] = useState("");

  const loras = useQuery({
    queryKey: ["loras"],
    queryFn: () => api.get<LoraList>("/api/v1/loras"),
    enabled: showStyle,
    staleTime: 300000,
  });

  const generate = useMutation({
    mutationFn: () =>
      api.post<JobAccepted>("/api/v1/jobs", {
        operation: "music.generate",
        model_id: "ace-step-1.5",
        music_description: mood ? `${desc}, ${mood.toLowerCase()} mood` : desc,
        duration_seconds: duration,
        instrumental,
        ...(loraId ? { lora_id: loraId } : {}),
        outputs: ["mix_wav"],
      }),
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
  const busy = generate.isPending || (status ? status !== "succeeded" && status !== "failed" : false);
  const result = (artifacts.data?.artifacts || []).filter((a) => a.mime.startsWith("audio/"))[0];
  const resultUrl = result ? urls.data?.[result.asset_id] : undefined;

  return (
    <div className={`card create-panel create-${variant}`}>
      <div className="create-input-row">
        <span className="input-spark" aria-hidden>✦</span>
        <textarea
          rows={variant === "wide" ? 1 : variant === "panel" ? 4 : 3}
          maxLength={500}
          value={desc}
          onChange={(e) => setDesc(e.target.value)}
          placeholder="Describe the music you want…"
        />
        {variant !== "wide" && <span className="char-count">{desc.length}/500</span>}
        {variant === "wide" && (
          <button className="btn btn-primary btn-lg gen-wide" disabled={!!busy} onClick={() => generate.mutate()}>
            {busy ? "✦ Generating…" : "✦ Generate"} →
          </button>
        )}
      </div>
      <div className="create-controls">
        {showStyle && (
          <div className="field ctrl">
            <span className="ctrl-icon" aria-hidden>♪</span>
            <div className="field">
              <label>Style</label>
              <select value={loraId} onChange={(e) => setLoraId(e.target.value)}>
                <option value="">Auto</option>
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
            {busy ? "✦ Generating…" : "✦ Generate"} →
          </button>
        )}
      </div>
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
      {result && resultUrl && (
        <div className="track-row" style={{ marginTop: 14, borderBottom: 0 }}>
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
      )}
    </div>
  );
}
