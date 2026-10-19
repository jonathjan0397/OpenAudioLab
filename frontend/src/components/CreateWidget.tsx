import { useEffect, useState } from "react";
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

const EXAMPLES = [
  "A dreamy indie pop song about chasing a brighter tomorrow",
  "Rainy lo-fi beat for a late-night study session",
  "Anthemic stadium rock about never giving up",
  "Smooth jazz in a smoky café at midnight",
  "Upbeat synthwave about driving through neon city lights",
  "Folk ballad about coming home after a long winter",
  "Funk groove about a dance-off on a Saturday night",
  "Cinematic orchestral swell for a hero's last stand",
  "Reggae sunset vibe about taking life slow",
  "Hyperpop glitch about falling in love with a robot",
  "Country twang about a dirt road and an old pickup",
  "Ambient drone for deep focus and slow breathing",
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
  const [title, setTitle] = useState("");
  const [draftTitle, setDraftTitle] = useState("");
  const [draftOpen, setDraftOpen] = useState(false);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [moreOpen, setMoreOpen] = useState(false);
  const [desc, setDesc] = useState(() => EXAMPLES[Math.floor(Math.random() * EXAMPLES.length)]);
  const [style, setStyle] = useState("");
  const [lyrics, setLyrics] = useState("");
  const [drafted, setDrafted] = useState(false);
  const [duration] = useState(120);
  const [instrumental, setInstrumental] = useState(false);
  const [mood, setMood] = useState("");
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
      api.post<{ lyrics: string; style: string; mood?: string; title?: string }>("/api/v1/llm/draft", {
        prompt: desc,
        duration_seconds: duration,
        instrumental,
        lora_tags: (loras.data?.loras || []).flatMap((l) => [l.name.toLowerCase()]),
      }),
    onSuccess: (d) => {
      setLyrics(d.lyrics);
      setStyle(d.style);
      setMood(d.mood || "");
      setDraftTitle(d.title || "");
      setDrafted(true);
      setDraftOpen(true);
      setError("");
    },
    onError: (e: Error) => setError(e.message),
  });

  const canDraft = desc.trim().length >= 8;

  const generate = useMutation({
    mutationFn: async () => {
      let finalLyrics = lyrics.trim() || undefined;
      if (!instrumental && !finalLyrics) {
        const r = await api.post<{ text: string }>("/api/v1/llm/lyrics", { prompt: desc, mode: "write" });
        finalLyrics = r.text;
      }
      const controls: Record<string, unknown> = {};
      if (mood) controls.mood = mood.toLowerCase();
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
          ...((title.trim() || draftTitle) ? { title: (title.trim() || draftTitle).slice(0, 200) } : {}),
          ...(finalLyrics && !instrumental ? { lyrics: finalLyrics, lyrics_origin: "frontend_llm" } : {}),
          controls,
          duration_seconds: mode === "create" ? undefined : mode === "extend" ? Math.min(duration + 60, 600) : duration,
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
    const append = (v: string) => {
      const clean = v.replace(/\s*,?\s*$/, "");
      return clean ? `${clean}, ${tag}` : tag;
    };
    if (easy) setStyle((v) => append(v));
    else setDesc((v) => (v.includes(tag) ? v : append(v)));
  };

  const toggleMode = () => {
    const next = !easy;
    setEasy(next);
    localStorage.setItem("oal-create-mode", next ? "simple" : "advanced");
  };

  return (
    <div className={`card create-panel create-${variant}`}>
      <div className="create-mode-row">
        <div className="segmented">
          <button type="button" className={easy ? "active" : ""} onClick={() => { setEasy(true); localStorage.setItem("oal-create-mode", "simple"); }}>Simple</button>
          <button type="button" className={!easy ? "active" : ""} onClick={toggleMode}>Advanced</button>
        </div>
        <span className="sub" style={{ fontSize: 12, color: "var(--muted)" }}>
          {easy ? "Describe your song — AI writes lyrics, style & title" : "Full control: title, lyrics, styles, vocals"}
        </span>
      </div>

      {easy ? (
        <>
          <div className="create-input-row">
            <span className="input-spark" aria-hidden>✦</span>
            <textarea
              rows={variant === "wide" ? 1 : 2}
              maxLength={500}
              value={desc}
              onChange={(e) => setDesc(e.target.value)}
              placeholder="Describe your song… e.g. rainy lo-fi study night"
            />
            {variant !== "wide" && <span className="char-count">{desc.length}/500</span>}
            <button
              type="button"
              className="btn btn-ghost ai-assistant-btn"
              disabled={!canDraft || draft.isPending}
              title={canDraft ? "Write lyrics, style & title with AI" : "Describe your song first (8+ characters)"}
              onClick={() => draft.mutate()}
            >
              {draft.isPending ? "✦ Writing…" : "✦ AI Assistant"}
            </button>
            {variant === "wide" && (
              <button className="btn btn-primary btn-lg gen-wide" disabled={!!busy} onClick={() => generate.mutate()}>
                {busy ? "✦ Generating…" : actionLabel} →
              </button>
            )}
          </div>
          <div className="create-simple-row">
            <input className="create-title" placeholder="Song title (optional)" maxLength={200} value={title} onChange={(e) => setTitle(e.target.value)} />
            {drafted && (
              <button type="button" className="draft-summary" onClick={() => setDraftOpen((o) => !o)}>
                ✦ AI draft {draftOpen ? "▴" : "▾"}
                {style && <span className="sub" style={{ fontSize: 11 }}> {style.slice(0, 44)}{style.length > 44 ? "…" : ""}</span>}
              </button>
            )}
            {draft.isPending && <span className="sub" style={{ fontSize: 12 }}>✦ writing…</span>}
          </div>
          {drafted && draftOpen && (
            <div className="create-review">
              <div className="field">
                <label>Style tags</label>
                <div className="style-inline">
                  <input value={style} onChange={(e) => setStyle(e.target.value)} placeholder="lofi, chill, female vocals" />
                  <button type="button" className="btn btn-ghost" title="Style cheat sheet" onClick={() => setSheetOpen(true)}>♬</button>
                  <button type="button" className="btn btn-ghost" title="Rewrite with AI" disabled={draft.isPending} onClick={() => draft.mutate()}>♻</button>
                </div>
              </div>
              {!instrumental && (
                <div className="field">
                  <label>Lyrics</label>
                  <textarea rows={4} value={lyrics} onChange={(e) => setLyrics(e.target.value)} placeholder="[Verse]…" />
                </div>
              )}
            </div>
          )}
        </>
      ) : (
        <>
          <div className="create-adv-grid">
            <div className="field">
              <label>Song title</label>
              <input placeholder="Untitled" maxLength={200} value={title} onChange={(e) => setTitle(e.target.value)} />
            </div>
            {!instrumental && (
              <div className="field">
                <label>Lead singer</label>
                <div className="segmented">
                  <button type="button" className={gender === "" ? "active" : ""} onClick={() => setGender("")}>Any</button>
                  <button type="button" className={gender === "male" ? "active" : ""} onClick={() => setGender("male")}>Male</button>
                  <button type="button" className={gender === "female" ? "active" : ""} onClick={() => setGender("female")}>Female</button>
                </div>
              </div>
            )}
            <div className="field">
              <label>Vocals</label>
              <div className="segmented">
                <button type="button" className={!instrumental ? "active" : ""} onClick={() => setInstrumental(false)}>Vocal</button>
                <button type="button" className={instrumental ? "active" : ""} onClick={() => setInstrumental(true)}>Instr.</button>
              </div>
            </div>
          </div>
          {!instrumental && (
            <div className="field create-gap">
              <label>Lyrics</label>
              <textarea rows={4} value={lyrics} onChange={(e) => setLyrics(e.target.value)} placeholder="[Verse]…[Chorus]… — leave empty and AI will write them" />
            </div>
          )}
          <div className="field create-gap">
            <label>Styles of music</label>
            <div className="style-inline">
              <textarea
                rows={2}
                maxLength={500}
                value={desc}
                onChange={(e) => setDesc(e.target.value)}
                placeholder="e.g. dreamy indie pop, warm female vocals, 110 bpm"
              />
              <button type="button" className="btn btn-ghost" title="Style cheat sheet" onClick={() => setSheetOpen(true)}>♬ cheat sheet</button>
            </div>
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
            </div>
          </div>
          <div className="create-bottom-row">
            <button type="button" className="more-toggle" onClick={() => setMoreOpen((o) => !o)}>More controls {moreOpen ? "▴" : "▾"}</button>
            <span className="spacer" />
            <button className="btn btn-primary" disabled={!!busy} onClick={() => generate.mutate()}>
              {busy ? "✦ Generating…" : actionLabel} →
            </button>
          </div>
          {moreOpen && (
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
                  <label>Language</label>
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
              {showStyle && (
                <div className="field ctrl">
                  <div className="field">
                    <label>Style model</label>
                    <select value={loraId} onChange={(e) => setLoraId(e.target.value)}>
                      <option value="">Auto (match tags)</option>
                      {(loras.data?.loras || []).map((l) => (
                        <option key={l.id} value={l.id}>{l.name}</option>
                      ))}
                    </select>
                  </div>
                </div>
              )}
            </div>
          )}
        </>
      )}

      {easy && (
        <div className="create-controls">
          <div className="field ctrl">
            <div className="field">
              <label>Vocals</label>
              <div className="segmented">
                <button type="button" className={!instrumental ? "active" : ""} onClick={() => setInstrumental(false)}>Vocal</button>
                <button type="button" className={instrumental ? "active" : ""} onClick={() => setInstrumental(true)}>Instrumental</button>
              </div>
            </div>
          </div>
          {!instrumental && (
            <div className="field ctrl">
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
          {showStyle && (
            <div className="field ctrl">
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
          {variant !== "wide" && (
            <button className="btn btn-primary btn-lg" disabled={!!busy} onClick={() => generate.mutate()}>
              {busy ? "✦ Generating…" : actionLabel} →
            </button>
          )}
        </div>
      )}
      {easy && <div className="style-chips" style={{ marginTop: 4 }}>
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
        <button type="button" className="chip chip-link" onClick={() => setSheetOpen(true)}>♬ cheat sheet</button>
      </div>}

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
      {sheetOpen && <StyleSheetModal onPick={addChip} onClose={() => setSheetOpen(false)} />}
    </div>
  );
}

interface CheatSheet {
  categories: { name: string; tags: string[] }[];
  lora_tags: string[];
}

function StyleSheetModal({ onPick, onClose }: { onPick: (tag: string) => void; onClose: () => void }) {
  const [picked, setPicked] = useState<string[]>([]);
  const sheet = useQuery({
    queryKey: ["style-cheatsheet"],
    queryFn: () => api.get<CheatSheet>("/api/v1/styles/cheatsheet"),
    staleTime: 600000,
  });
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  const pick = (tag: string) => {
    onPick(tag);
    setPicked((p) => (p.includes(tag) ? p : [...p, tag]));
  };
  return (
    <div className="drawer-overlay" onClick={onClose}>
      <div className="sheet-modal" onClick={(e) => e.stopPropagation()}>
        <div className="sheet-head">
          <h3>Style cheat sheet</h3>
          <span className="spacer" />
          {picked.length > 0 && <span className="sub" style={{ fontSize: 12 }}>+{picked.length} added</span>}
          <button type="button" className="btn btn-ghost" onClick={onClose} aria-label="Close">✕</button>
        </div>
        <div className="sheet-body">
          {(sheet.data?.lora_tags || []).length > 0 && (
            <div className="sheet-cat">
              <label>♪ Your style models</label>
              <div className="sheet-tags">
                {(sheet.data?.lora_tags || []).map((t) => (
                  <button key={t} type="button" className={`chip${picked.includes(t) ? " chip-picked" : ""}`} onClick={() => pick(t)}>+ {t}</button>
                ))}
              </div>
            </div>
          )}
          {(sheet.data?.categories || []).map((c) => (
            <div className="sheet-cat" key={c.name}>
              <label>{c.name}</label>
              <div className="sheet-tags">
                {c.tags.map((t) => (
                  <button key={t} type="button" className={`chip${picked.includes(t) ? " chip-picked" : ""}`} onClick={() => pick(t)}>+ {t}</button>
                ))}
              </div>
            </div>
          ))}
          {!sheet.data && <p className="sub">Loading…</p>}
        </div>
        <div className="sheet-foot">
          <span className="spacer" />
          <button type="button" className="btn btn-primary" onClick={onClose}>Done</button>
        </div>
      </div>
    </div>
  );
}
