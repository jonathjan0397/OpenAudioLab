import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError, AuthUser, GenerationQuote, GuestAllowance, ModelSelection, PolicyPayload } from "../api";
import { buildGenerationRequest } from "../lib/generation";
import ArtworkTile from "./ArtworkTile";
import Waveform from "./Waveform";
import { usePlayer } from "./PlayerContext";
import { useWorkspace } from "./WorkspaceContext";
import { exportArtifact } from "./social";
import { fmtTime, humanizeStage, Progress } from "./ui";

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

export const DRAFT_KEY = "oal-create-draft-v2";

interface DraftSnapshot {
  title: string;
  desc: string;
  styles: string;
  lyrics: string;
  mood: string;
  drafted: boolean;
}

function loadDraft(): Partial<DraftSnapshot & Record<string, unknown>> {
  try {
    return JSON.parse(localStorage.getItem(DRAFT_KEY) || "{}");
  } catch {
    return {};
  }
}

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
  const qc = useQueryClient();
  const { activeId, activeArtist } = useWorkspace();
  const me = useQuery({
    queryKey: ["me"],
    queryFn: () => api.get<{ user: AuthUser }>("/api/v1/auth/me"),
    retry: false,
  });
  const guest = useQuery({
    queryKey: ["guest"],
    queryFn: () => api.post<GuestAllowance>("/api/v1/auth/guest"),
    enabled: me.isFetched && !me.data,
    staleTime: 15000,
  });
  const policies = useQuery({
    queryKey: ["policies"],
    queryFn: () => api.get<PolicyPayload>("/api/v1/policies"),
    staleTime: 300000,
  });
  const caps = useQuery({
    queryKey: ["model-caps", "ace-step-1.5"],
    queryFn: () =>
      api.get<{
        supported_controls: string[];
        supported_task_types: string[];
        controls: { key: string; label: string; applicable: boolean; min?: number | null; max?: number | null; default?: number | null; description?: string }[];
      }>("/api/v1/models/ace-step-1.5"),
    staleTime: 300000,
  });
  const catalog = useQuery({
    queryKey: ["model-selections"],
    queryFn: () => api.get<ModelSelection[]>("/api/v1/model-selections"),
    staleTime: 300000,
  });
  const [modelSelection, setModelSelection] = useState("ace-step-1.5-turbo");
  const [quote, setQuote] = useState<GenerationQuote | null>(null);
  const selectedModel = (catalog.data || []).find((m) => m.model_selection === modelSelection) || null;
  const selectedProfile = selectedModel?.profiles?.[0] || null;
  const stepsRange = selectedProfile?.control_ranges?.inference_steps ?? null;
  const premiumSelected = !!selectedProfile && selectedProfile.requires_paid;
  const isGuest = me.isFetched && !me.data;
  const guestPolicyAccepted = Boolean(guest.data?.policy_accepted);
  const [policyAccepted, setPolicyAccepted] = useState(false);
  const guestQuotaExhausted = isGuest && (guest.data?.remaining ?? 1) <= 0;
  const guestPolicyMissing = isGuest && !guestPolicyAccepted && !policyAccepted;
  const saved = loadDraft();
  const [easy, setEasy] = useState(() => localStorage.getItem("oal-create-mode") !== "advanced");
  const [title, setTitle] = useState(String(saved.title || ""));
  const [draftTitle, setDraftTitle] = useState("");
  const [draftOpen, setDraftOpen] = useState(Boolean(saved.draftOpen ?? false));
  const [sheetOpen, setSheetOpen] = useState(false);
  const [moreOpen, setMoreOpen] = useState(false);
  const [desc, setDesc] = useState(String(saved.desc || ""));
  const [styles, setStyles] = useState(String(saved.styles || ""));
  const [lyrics, setLyrics] = useState(String(saved.lyrics || ""));
  const [drafted, setDrafted] = useState(Boolean(saved.drafted ?? false));
  const [duration, setDuration] = useState(Number(saved.duration ?? 120));
  const [instrumental, setInstrumental] = useState(Boolean(saved.instrumental ?? false));
  const [mood, setMood] = useState(String(saved.mood || ""));
  const [gender, setGender] = useState(String(saved.gender || ""));
  const [loraId, setLoraId] = useState(String(saved.loraId || ""));

  const wsArtistCompatible =
    !isGuest && !loraId && !!activeArtist && activeArtist.applicable &&
    activeArtist.adapter_model_selection === modelSelection;
  const workspaceAdapterId = wsArtistCompatible ? activeArtist!.default_adapter_id || undefined : undefined;
  const wsArtistBlocked =
    !isGuest && !!activeArtist && !wsArtistCompatible &&
    (!!loraId || !activeArtist.applicable || activeArtist.adapter_model_selection !== modelSelection);
  const [bpm, setBpm] = useState(String(saved.bpm || ""));
  const [keyScale, setKeyScale] = useState(String(saved.keyScale || ""));
  const [timeSignature, setTimeSignature] = useState(String(saved.timeSignature || ""));
  const [language, setLanguage] = useState(String(saved.language || ""));
  const [shift, setShift] = useState(Number(saved.shift ?? 1));
  const [quality, setQuality] = useState(Number(saved.quality ?? 8));
  const [variations, setVariations] = useState(Number(saved.variations ?? 1));
  const [chipSeed, setChipSeed] = useState(() => Math.floor(Math.random() * 1e9));
  const [jobId, setJobId] = useState<string | null>(() => sessionStorage.getItem("oal-active-job"));
  const [error, setError] = useState("");
  const [history, setHistory] = useState<DraftSnapshot[]>([]);
  const [lockTitle, setLockTitle] = useState(false);
  const [lockLyrics, setLockLyrics] = useState(false);
  const [lockStyle, setLockStyle] = useState(false);

  useEffect(() => {
    const max = guest.data?.max_duration_seconds;
    if (isGuest && max && duration > max) setDuration(max);
  }, [duration, guest.data?.max_duration_seconds, isGuest]);

  useEffect(() => {
    localStorage.setItem(
      DRAFT_KEY,
      JSON.stringify({
        title,
        desc,
        styles,
        lyrics,
        mood,
        instrumental,
        gender,
        loraId,
        bpm,
        keyScale,
        timeSignature,
        language,
        shift,
        quality,
        variations,
        duration,
        drafted,
        draftOpen,
        modelSelection,
      })
    );
  }, [title, desc, styles, lyrics, mood, instrumental, gender, loraId, bpm, keyScale, timeSignature, language, shift, quality, variations, duration, drafted, draftOpen, modelSelection]);

  // When the selected model's step band changes, reset Quality to that profile's
  // default so a value carried from another model (e.g. Turbo's 8, or a premium
  // 100 when switching to Turbo) can never be out of the new band.
  useEffect(() => {
    if (stepsRange?.default != null) setQuality(stepsRange.default);
  }, [stepsRange?.default, stepsRange?.min, stepsRange?.max]);

  const snapshot = (): DraftSnapshot => ({ title, desc, styles, lyrics, mood, drafted });
  const pushHistory = () => setHistory((h) => [...h.slice(-9), snapshot()]);
  const undoDraft = () => {
    const prev = history[history.length - 1];
    if (!prev) return;
    setTitle(prev.title);
    setDesc(prev.desc);
    setStyles(prev.styles);
    setLyrics(prev.lyrics);
    setMood(prev.mood);
    setDrafted(prev.drafted);
    setHistory((h) => h.slice(0, -1));
  };

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
      if (!lockLyrics) setLyrics(d.lyrics);
      if (!lockStyle) setStyles(d.style);
      if (!lockTitle && d.title) setTitle(d.title);
      setMood(d.mood || "");
      setDraftTitle(d.title || "");
      setDrafted(true);
      setDraftOpen(true);
      setError("");
    },
    onError: (e: Error) => setError(e.message),
  });

  const rewriteLyrics = useMutation({
    mutationFn: () =>
      api.post<{ text: string }>("/api/v1/llm/lyrics", {
        prompt: [desc, styles].filter(Boolean).join(", "),
        mode: lyrics.trim() ? "humanize" : "write",
        lyrics,
      }),
    onSuccess: (d) => {
      if (!lockLyrics) setLyrics(d.text);
      setDrafted(true);
      setError("");
    },
    onError: (e: Error) => setError(e.message),
  });

  const rewriteStyle = useMutation({
    mutationFn: () =>
      api.post<{ style_prompt: string }>("/api/v1/llm/style-prompt", {
        description: [desc, styles].filter(Boolean).join(" ") || desc,
      }),
    onSuccess: (d) => {
      if (!lockStyle) setStyles(d.style_prompt);
      setDrafted(true);
      setError("");
    },
    onError: (e: Error) => setError(e.message),
  });

  const rewriteTitle = useMutation({
    mutationFn: () =>
      api.post<{ title: string }>("/api/v1/llm/title", {
        prompt: desc,
        lyrics,
      }),
    onSuccess: (d) => {
      if (!lockTitle) setTitle(d.title);
      setError("");
    },
    onError: (e: Error) => setError(e.message),
  });

  const canDraft = desc.trim().length >= 8;
  const assistantBusy = draft.isPending || rewriteLyrics.isPending || rewriteStyle.isPending || rewriteTitle.isPending;

  const generate = useMutation({
    mutationFn: async () => {
      const userLyrics = lyrics;
      let finalLyrics = userLyrics;
      let lyricsProvided = userLyrics.trim().length > 0;
      if (!instrumental && !lyricsProvided) {
        const r = await api.post<{ text: string }>("/api/v1/llm/lyrics", { prompt: desc, mode: "write" });
        finalLyrics = r.text;
      }
      const durationSeconds = mode === "extend" ? Math.min(duration + 60, 600) : duration;
      const body = buildGenerationRequest(
        {
          idea: desc,
          styles,
          mood,
          gender,
          bpm,
          keyScale,
          timeSignature,
          language,
          shift,
          quality,
          guidance: 0,
          variations,
          title: title.trim() || draftTitle,
          lyrics: finalLyrics,
          lyricsProvided,
          instrumental,
          durationSeconds,
          loraId,
          modelSelection: premiumSelected ? modelSelection : undefined,
          executionProfileId: premiumSelected ? selectedProfile!.execution_profile_id : undefined,
          seed: mode === "remix" ? Math.floor(Math.random() * 1_000_000_000) : undefined,
          workspaceId: isGuest ? undefined : activeId || undefined,
          voiceAdapterId: workspaceAdapterId,
        },
        { supportedControls: caps.data?.supported_controls, controlRanges: selectedProfile?.control_ranges },
      );
      // Premium selection: get a server quote first, then bind it. The quote and
      // the job carry identical fields (the server hash excludes quote_id).
      if (premiumSelected) {
        const q = await api.post<GenerationQuote>("/api/v1/generation/quote", body);
        body.quote_id = q.quote_id;
        setQuote(q);
      }
      if (isGuest) {
        body.policy_accepted = guestPolicyAccepted || policyAccepted;
        if (policies.data?.version) body.policy_version = policies.data.version;
      }
      return api.post<JobAccepted>(
        "/api/v1/jobs",
        body,
        { "Idempotency-Key": crypto.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}` }
      );
    },
    onSuccess: (d) => {
      setError("");
      setJobId(d.job_id);
      qc.invalidateQueries({ queryKey: ["guest"] });
    },
    onError: (e: unknown) => {
      const err = e instanceof ApiError ? e : null;
      setError(err?.controlHint() || err?.message || "Generation failed. Please try again.");
      qc.invalidateQueries({ queryKey: ["guest"] });
    },
  });

  useEffect(() => {
    if (jobId) sessionStorage.setItem("oal-active-job", jobId);
    else sessionStorage.removeItem("oal-active-job");
  }, [jobId]);

  const retry = useMutation({
    mutationFn: () => api.post<JobDetail>(`/api/v1/jobs/${jobId}/retry`),
    onSuccess: () => setError(""),
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
  const busy = generate.isPending || assistantBusy || (status ? status !== "succeeded" && status !== "failed" : false);
  const actionLabel = mode === "remix" ? "✦ Remix" : mode === "extend" ? "✦ Extend" : "✦ Generate";
  const results = (artifacts.data?.artifacts || []).filter((a) => a.mime.startsWith("audio/"));

  const addChip = (tag: string) => {
    const append = (v: string) => {
      const clean = v.replace(/\s*,?\s*$/, "");
      return clean ? `${clean}, ${tag}` : tag;
    };
    setStyles((v) => (v.includes(tag) ? v : append(v)));
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

      {isGuest && (
        <div className="guest-access-row">
          <span className="sub" style={{ fontSize: 12 }}>
            Guest: {guest.data ? `${guest.data.remaining}/${guest.data.limit} songs left today` : "checking allowance…"}
            {guest.data ? ` · max ${Math.round(guest.data.max_duration_seconds / 60)} min` : ""}
          </span>
          {guestPolicyMissing && (
            <label className="auth-policy" style={{ margin: 0 }}>
              <input type="checkbox" checked={policyAccepted} onChange={(e) => setPolicyAccepted(e.target.checked)} />
              <span>
                I accept the <a className="link" href="/policies">Terms, Abuse Policy, and Privacy Notice</a>.
              </span>
            </label>
          )}
          {guestQuotaExhausted && <span className="pill err">Daily guest limit reached. Sign in or wait for UTC midnight.</span>}
        </div>
      )}

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
              disabled={!canDraft || assistantBusy}
              title={canDraft ? "Write lyrics, style & title with AI" : "Describe your song first (8+ characters)"}
              onClick={() => { pushHistory(); draft.mutate(); }}
            >
              {draft.isPending ? "✦ Writing…" : "✦ AI Assistant"}
            </button>
            {history.length > 0 && (
              <button type="button" className="btn btn-ghost" title="Undo last AI draft change" onClick={undoDraft}>
                ↶ Undo
              </button>
            )}
            {variant === "wide" && (
              <button className="btn btn-primary btn-lg gen-wide" disabled={!!busy || guestQuotaExhausted || guestPolicyMissing} onClick={() => generate.mutate()}>
                {busy ? "✦ Generating…" : actionLabel} →
              </button>
            )}
          </div>
          <div className="create-examples" role="group" aria-label="Song idea suggestions">
            {EXAMPLES.slice(0, 4).map((ex) => (
              <button key={ex} type="button" className="example-chip" onClick={() => { pushHistory(); setDesc(ex); }} title="Use this idea">
                {ex}
              </button>
            ))}
          </div>
          <div className="create-simple-row">
            <input className="create-title" placeholder="Song title (optional)" maxLength={200} value={title} onChange={(e) => setTitle(e.target.value)} />
            {drafted && (
              <button type="button" className="draft-summary" onClick={() => setDraftOpen((o) => !o)}>
                ✦ AI draft {draftOpen ? "▴" : "▾"}
                {styles && <span className="sub" style={{ fontSize: 11 }}> {styles.slice(0, 44)}{styles.length > 44 ? "…" : ""}</span>}
              </button>
            )}
            {draft.isPending && <span className="sub" style={{ fontSize: 12 }}>✦ writing…</span>}
          </div>
          {drafted && draftOpen && (
            <div className="create-review">
              <div className="field">
                <label>Title</label>
                <div className="style-inline">
                  <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Untitled" maxLength={200} />
                  <button type="button" className="btn btn-ghost" title={lockTitle ? "Unlock title" : "Lock title"} onClick={() => setLockTitle((v) => !v)}>{lockTitle ? "🔒" : "🔓"}</button>
                  <button type="button" className="btn btn-ghost" title="Rewrite title with AI" disabled={rewriteTitle.isPending} onClick={() => { pushHistory(); rewriteTitle.mutate(); }}>♻</button>
                </div>
              </div>
              <div className="field">
                <label>Style tags</label>
                <div className="style-inline">
                  <input value={styles} onChange={(e) => setStyles(e.target.value)} placeholder="lofi, chill, female vocals" />
                  <button type="button" className="btn btn-ghost" title={lockStyle ? "Unlock style" : "Lock style"} onClick={() => setLockStyle((v) => !v)}>{lockStyle ? "🔒" : "🔓"}</button>
                  <button type="button" className="btn btn-ghost" title="Style cheat sheet" onClick={() => setSheetOpen(true)}>♬</button>
                  <button type="button" className="btn btn-ghost" title="Rewrite style with AI" disabled={rewriteStyle.isPending} onClick={() => { pushHistory(); rewriteStyle.mutate(); }}>♻</button>
                </div>
              </div>
              {!instrumental && (
                <div className="field">
                  <label>Lyrics</label>
                  <textarea rows={4} value={lyrics} onChange={(e) => setLyrics(e.target.value)} placeholder="[Verse]…" />
                  <div className="style-inline" style={{ marginTop: 6 }}>
                    <button type="button" className="btn btn-ghost" title={lockLyrics ? "Unlock lyrics" : "Lock lyrics"} onClick={() => setLockLyrics((v) => !v)}>{lockLyrics ? "🔒 lyrics" : "🔓 lyrics"}</button>
                    <button type="button" className="btn btn-ghost" title="Rewrite or humanize lyrics" disabled={rewriteLyrics.isPending} onClick={() => { pushHistory(); rewriteLyrics.mutate(); }}>♻ lyrics</button>
                  </div>
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
              <div className="style-inline" style={{ marginTop: 6 }}>
                <button type="button" className="btn btn-ghost" title={lockLyrics ? "Unlock lyrics" : "Lock lyrics"} onClick={() => setLockLyrics((v) => !v)}>{lockLyrics ? "🔒 lyrics" : "🔓 lyrics"}</button>
                <button type="button" className="btn btn-ghost" title="Rewrite or humanize lyrics" disabled={rewriteLyrics.isPending} onClick={() => { pushHistory(); rewriteLyrics.mutate(); }}>♻ lyrics</button>
                <button type="button" className="btn btn-ghost" title="Rewrite title with AI" disabled={rewriteTitle.isPending} onClick={() => { pushHistory(); rewriteTitle.mutate(); }}>♻ title</button>
              </div>
            </div>
          )}
          <div className="field create-gap">
            <label>Song idea</label>
            <textarea
              rows={2}
              maxLength={500}
              value={desc}
              onChange={(e) => setDesc(e.target.value)}
              placeholder="Describe the scene, story, or feeling"
            />
          </div>
          <div className="field create-gap">
            <label>Styles of music</label>
            <div className="style-inline">
              <textarea
                rows={2}
                maxLength={500}
                value={styles}
                onChange={(e) => setStyles(e.target.value)}
                placeholder="e.g. dreamy indie pop, warm female vocals, 110 bpm"
              />
              <button type="button" className="btn btn-ghost" title={lockStyle ? "Unlock style" : "Lock style"} onClick={() => setLockStyle((v) => !v)}>{lockStyle ? "🔒" : "🔓"}</button>
              <button type="button" className="btn btn-ghost" title="Style cheat sheet" onClick={() => setSheetOpen(true)}>♬ cheat sheet</button>
              <button type="button" className="btn btn-ghost" title="Rewrite style with AI" disabled={rewriteStyle.isPending} onClick={() => { pushHistory(); rewriteStyle.mutate(); }}>♻</button>
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
          {(wsArtistCompatible || wsArtistBlocked) && (
            <div className={`ws-artist-note${wsArtistCompatible ? " on" : " off"}`}>
              {wsArtistCompatible
                ? `♪ ${activeArtist!.name} — this workspace's artist will be applied`
                : `${activeArtist!.name} — voice adapter not applied (pick the model it was trained for, or train it for this model)`}
            </div>
          )}
          <div className="create-bottom-row">
            <button type="button" className="more-toggle" onClick={() => setMoreOpen((o) => !o)}>More controls {moreOpen ? "▴" : "▾"}</button>
            <span className="spacer" />
            <button className="btn btn-primary" disabled={!!busy || guestQuotaExhausted || guestPolicyMissing} onClick={() => generate.mutate()}>
              {busy ? "✦ Generating…" : actionLabel} →
            </button>
          </div>
          {moreOpen && (
            <div className="create-advanced">
              <div className="field ctrl">
                <div className="field" style={{ width: "100%" }}>
                  <label>Model</label>
                  <div className="model-cards" role="radiogroup" aria-label="Model selection">
                    {(catalog.data || []).map((m) => {
                      const p = m.profiles[0];
                      const selectable = p.runnable && (!p.requires_paid || !!me.data?.user);
                      const selected = m.model_selection === modelSelection;
                      const badge = !p.runnable ? "unavailable" : p.experimental ? "experimental" : p.requires_paid ? "paid" : "basic";
                      return (
                        <button
                          key={m.model_selection}
                          type="button"
                          role="radio"
                          aria-checked={selected}
                          disabled={!selectable}
                          className={`model-card${selected ? " on" : ""}`}
                          title={p.quality_note}
                          onClick={() => { setModelSelection(m.model_selection); setQuote(null); }}
                        >
                          <span className="mc-name">{m.display_name}</span>
                          <span className={`mc-badge b-${badge}`}>{badge}</span>
                          <span className="mc-cost">{p.pricing.multiplier.toFixed(2)}× / take</span>
                        </button>
                      );
                    })}
                  </div>
                  {selectedProfile?.control_ranges?.guidance_scale?.locked && (
                    <span className="sub" style={{ fontSize: 11 }}>
                      {selectedModel?.display_name}: {selectedProfile.control_ranges.inference_steps.locked ? "8 steps" : ""} · effective CFG {selectedProfile.control_ranges.guidance_scale.default} (fixed).
                    </span>
                  )}
                  {premiumSelected && quote && (
                    <span className="sub" style={{ fontSize: 11 }}>
                      Quoted: {quote.reserved_credits} credits{quote.balance != null ? ` · balance ${quote.balance}` : ""}
                    </span>
                  )}
                </div>
              </div>
              <div className="field ctrl">
                <div className="field">
                  <label>Duration</label>
                  <select value={duration} onChange={(e) => setDuration(Number(e.target.value))}>
                    <option value={60}>60s</option>
                    <option value={120}>120s</option>
                    <option value={180}>180s</option>
                    <option value={240}>240s</option>
                  </select>
                </div>
              </div>
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
                  <label>Time sig</label>
                  <input value={timeSignature} onChange={(e) => setTimeSignature(e.target.value)} placeholder="Auto" maxLength={8} />
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
                  <label>Timestep Shift {shift.toFixed(2)}</label>
                  <input
                    type="range"
                    min={1}
                    max={5}
                    step={0.25}
                    value={shift}
                    disabled
                    title="Not applied to the current Turbo model. Timestep shift only affects base (non-turbo) checkpoints."
                    onChange={(e) => setShift(Number(e.target.value))}
                  />
                  <span className="sub">No audible effect on Turbo — base models only.</span>
                </div>
              </div>
              <div className="field ctrl">
                <div className="field">
                  <label>Quality ({stepsRange?.locked ? `fixed ${stepsRange.default}` : `${quality} steps`})</label>
                  {stepsRange?.locked ? (
                    <input type="range" min={stepsRange.default} max={stepsRange.default} value={stepsRange.default} disabled />
                  ) : (
                    <input
                      type="range"
                      min={stepsRange?.min ?? 1}
                      max={stepsRange?.max ?? 128}
                      step={1}
                      value={quality}
                      onChange={(e) => setQuality(Number(e.target.value))}
                    />
                  )}
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
            <button className="btn btn-primary btn-lg" disabled={!!busy || guestQuotaExhausted || guestPolicyMissing} onClick={() => generate.mutate()}>
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
          <button className="btn" style={{ marginLeft: 10 }} disabled={retry.isPending} onClick={() => retry.mutate()}>
            {retry.isPending ? "Retrying…" : "Retry"}
          </button>
        </p>
      )}
      {busy && (
        <div style={{ marginTop: 14 }}>
          <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, color: "var(--muted)", marginBottom: 5 }}>
            <span>{humanizeStage(job.data?.stage) || "Queued"}</span>
            <span>{job.data?.progress != null ? `${Math.round(job.data.progress * 100)}%` : ""}</span>
          </div>
          <Progress value={job.data?.progress ?? null} />
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
              <a className="btn" href={`${resultUrl}${resultUrl.includes("?") ? "&" : "?"}download=1`} download>↓ WAV</a>
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
