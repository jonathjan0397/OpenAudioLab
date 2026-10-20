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

export interface BuildOptions {
  supportedControls?: Iterable<string>;
}

export function buildGenerationRequest(
  d: GenerationDraft,
  opts: BuildOptions = {},
): Record<string, unknown> {
  const supported = new Set(
    opts.supportedControls ? Array.from(opts.supportedControls) : DEFAULT_SUPPORTED_CONTROLS,
  );

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
  if (d.guidance) candidate.guidance_scale = Number(d.guidance);
  if (d.quality !== 8) candidate.inference_steps = d.quality;
  // shift is emitted only when the model declares it applicable; an intentional
  // 0 shift is preserved (explicit finite check, not truthiness).
  if (Number.isFinite(d.shift) && d.shift !== 1) candidate.shift = d.shift;
  if (d.variations > 1) candidate.variations = d.variations;

  const controls: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(candidate)) {
    if (supported.has(key)) controls[key] = value;
  }

  const body: Record<string, unknown> = {
    operation: "music.generate",
    model_id: "ace-step-1.5",
    music_description: caption || d.title.trim() || "Untitled",
    controls,
    duration_seconds: d.durationSeconds,
    instrumental: d.instrumental,
    outputs: ["mix_wav"],
  };
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
  return body;
}
