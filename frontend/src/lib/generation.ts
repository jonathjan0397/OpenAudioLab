// Canonical generation serializer shared by every theme and Studio.
// It keeps the song idea, raw style prompt, and the resolved non-lyric engine
// caption independent, and only emits controls the selected model supports AND
// consumes. Free-text idea/style must never go into the control bag.

export interface GenerationDraft {
  idea: string; // independent song idea (original user text)
  styles: string; // independent raw style direction
  mood: string; // mood/vocal preference (enum/selection)
  gender: string; // lead-singer preference
  bpm: string;
  keyScale: string;
  timeSignature: string;
  language: string;
  shift: number;
  quality: number; // inference steps
  guidance: number; // guidance scale (0 = unset/default)
  variations: number;
  title: string;
  lyrics: string; // exact approved lyrics (never re-trimmed)
  lyricsProvided: boolean; // true => human/approved, false => auto-written
  instrumental: boolean;
  durationSeconds: number;
  loraId: string;
  seed?: number;
  // Source-conditioned generation (cover/repaint). Left undefined for plain
  // text2music so the backend default applies unchanged.
  taskType?: string;
  srcAssetId?: string;
  referenceAssetId?: string;
  audioCoverStrength?: number;
  coverNoiseStrength?: number;
  repaintingStart?: number;
  repaintingEnd?: number;
  repaintMode?: string;
  repaintStrength?: number;
  chunkMaskMode?: string;
  // Multi-model selection. When modelSelection is set, model_id is omitted so the
  // server does not see a contradictory legacy model_id + model_selection pair.
  modelSelection?: string;
  executionProfileId?: string;
  quoteId?: string;
}

// Default capability set for the deployed ACE-Step 1.5 Turbo release. Callers
// that have loaded a model's capability list pass `supportedControls` to override
// (e.g. a base checkpoint that legitimately exposes `shift`).
const DEFAULT_SUPPORTED_CONTROLS = [
  "mood",
  "gender",
  "bpm",
  "key_scale",
  "time_signature",
  "vocal_language",
  "inference_steps",
  "guidance_scale",
  "variations",
];

export interface ControlRange {
  min: number;
  max: number;
  default: number;
  locked?: boolean;
}

export interface BuildOptions {
  supportedControls?: Iterable<string>;
  // Per-profile control bands from /model-selections. When supplied, the numeric
  // controls (steps/guidance/shift) are emitted only if they are in-band and differ
  // from the profile default, so a stale or turbo-shaped UI value can never trip the
  // backend's "out of range" rejection (the server then applies the profile default).
  // When omitted, the legacy truthy/default rules are kept (e.g. Studio's Turbo path).
  controlRanges?: Partial<Record<"inference_steps" | "guidance_scale" | "shift", ControlRange>>;
}

export function buildGenerationRequest(
  d: GenerationDraft,
  opts: BuildOptions = {},
): Record<string, unknown> {
  const supported = new Set(
    opts.supportedControls ? Array.from(opts.supportedControls) : DEFAULT_SUPPORTED_CONTROLS,
  );
  const ranges = opts.controlRanges ?? {};

  // Resolved non-lyric caption. Singer preference is folded in here because the
  // adapter has no dedicated gender field, so a control value alone would not
  // reach the audio; the caption does.
  const caption = [
    d.idea.trim(),
    d.mood ? `${d.mood.toLowerCase()} mood` : "",
    !d.instrumental && d.gender ? `${d.gender.toLowerCase()} vocals` : "",
    d.styles.trim(),
  ]
    .filter(Boolean)
    .join(", ")
    .slice(0, 2000);

  const candidate: Record<string, unknown> = {};
  if (d.mood) candidate.mood = d.mood.toLowerCase();
  if (!d.instrumental && d.gender) candidate.gender = d.gender;
  if (d.bpm) candidate.bpm = Number(d.bpm);
  if (d.keyScale) candidate.key_scale = d.keyScale;
  if (d.timeSignature) candidate.time_signature = d.timeSignature;
  if (d.language) candidate.vocal_language = d.language;
  // guidance/steps/shift: when a profile band is known, emit only an in-band value
  // that differs from the profile default (and is not locked); otherwise the server
  // applies the correct per-model default. Without bands, keep the legacy rules.
  const within = (v: number, r?: ControlRange) =>
    !!r && !r.locked && Number.isFinite(v) && v >= r.min && v <= r.max && v !== r.default;
  const g = Number(d.guidance);
  if (ranges.guidance_scale) {
    if (within(g, ranges.guidance_scale)) candidate.guidance_scale = g;
  } else if (g) candidate.guidance_scale = g;
  const q = Number(d.quality);
  if (ranges.inference_steps) {
    if (within(q, ranges.inference_steps)) candidate.inference_steps = q;
  } else if (q !== 8) candidate.inference_steps = q;
  // shift: UI default 1 means "unset" (slider disabled). Emit only an explicit,
  // in-band deviation, so a turbo profile (default 3.0) never sends a stale shift=1
  // that the legacy model_id path would reject; the server applies the profile default.
  const sh = Number(d.shift);
  if (Number.isFinite(sh) && sh !== 1) {
    if (!ranges.shift || (sh >= ranges.shift.min && sh <= ranges.shift.max)) candidate.shift = sh;
  }
  if (d.variations > 1) candidate.variations = d.variations;

  const controls: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(candidate)) {
    if (supported.has(key)) controls[key] = value;
  }

  const body: Record<string, unknown> = {
    operation: "music.generate",
    music_description: caption || d.title.trim() || "Untitled",
    controls,
    duration_seconds: d.durationSeconds,
    instrumental: d.instrumental,
    outputs: ["mix_wav"],
  };
  // model_selection requests omit the legacy model_id to avoid a contradiction;
  // otherwise keep the existing Turbo model_id for back-compat.
  if (d.modelSelection) {
    body.model_selection = d.modelSelection;
    if (d.executionProfileId) body.execution_profile_id = d.executionProfileId;
    if (d.quoteId) body.quote_id = d.quoteId;
  } else {
    body.model_id = "ace-step-1.5";
  }
  const idea = d.idea.trim();
  const stylePrompt = d.styles.trim();
  if (idea) body.song_idea = idea;
  if (stylePrompt) body.style_prompt = stylePrompt;
  const title = d.title.trim();
  if (title) body.title = title.slice(0, 200);
  if (!d.instrumental && d.lyrics.trim().length > 0) {
    body.lyrics = d.lyrics; // exact text; trim only for emptiness check above
    body.lyrics_origin = d.lyricsProvided ? "human" : "frontend_llm";
  }
  if (d.loraId) body.lora_id = d.loraId;
  if (typeof d.seed === "number") body.seed = d.seed;
  if (d.taskType) body.task_type = d.taskType;
  if (d.srcAssetId) body.src_asset_id = d.srcAssetId;
  if (d.referenceAssetId) body.reference_asset_id = d.referenceAssetId;
  if (typeof d.audioCoverStrength === "number") body.audio_cover_strength = d.audioCoverStrength;
  if (typeof d.coverNoiseStrength === "number") body.cover_noise_strength = d.coverNoiseStrength;
  if (typeof d.repaintingStart === "number") body.repainting_start = d.repaintingStart;
  if (typeof d.repaintingEnd === "number") body.repainting_end = d.repaintingEnd;
  if (d.repaintMode) body.repaint_mode = d.repaintMode;
  if (typeof d.repaintStrength === "number") body.repaint_strength = d.repaintStrength;
  if (d.chunkMaskMode) body.chunk_mask_mode = d.chunkMaskMode;
  return body;
}
