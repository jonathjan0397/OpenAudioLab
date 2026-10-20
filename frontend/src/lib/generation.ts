// Canonical generation serializer shared by every theme and Studio.
// It keeps the song idea, raw style prompt, and the resolved non-lyric engine
// caption independent, and only emits controls the selected model actually
// supports/consumes. Free-text idea/style must never go into the control bag.

export interface GenerationDraft {
  idea: string; // independent song idea (original user text)
  styles: string; // independent raw style direction
  mood: string; // vocal/mood preference (enum/selection)
  gender: string; // lead-singer preference
  bpm: string;
  keyScale: string;
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
}

// Controls the pinned ACE-Step 1.5 release both accepts and consumes
// (app/registry.py supported_controls). Keep in sync with the registry.
const SUPPORTED_CONTROLS = new Set([
  "mood",
  "gender",
  "bpm",
  "key_scale",
  "vocal_language",
  "inference_steps",
  "guidance_scale",
  "shift",
  "variations",
]);

export function buildGenerationRequest(d: GenerationDraft): Record<string, unknown> {
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

  const controls: Record<string, unknown> = {};
  if (d.mood) controls.mood = d.mood.toLowerCase();
  if (!d.instrumental && d.gender) controls.gender = d.gender;
  if (d.bpm) controls.bpm = Number(d.bpm);
  if (d.keyScale) controls.key_scale = d.keyScale;
  if (d.language) controls.vocal_language = d.language;
  if (d.guidance) controls.guidance_scale = Number(d.guidance);
  if (d.quality !== 8) controls.inference_steps = d.quality;
  // Preserve an intentional 0 shift: use explicit null/undefined check, not truthiness.
  if (Number.isFinite(d.shift) && d.shift !== 1) controls.shift = d.shift;
  if (d.variations > 1) controls.variations = d.variations;
  for (const key of Object.keys(controls)) {
    if (!SUPPORTED_CONTROLS.has(key)) delete controls[key];
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
  return body;
}
