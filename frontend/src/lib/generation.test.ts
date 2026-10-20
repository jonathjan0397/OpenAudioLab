import { describe, it, expect } from "vitest";

import { buildGenerationRequest, type GenerationDraft } from "./generation";

const base: GenerationDraft = {
  idea: "",
  styles: "",
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
  title: "",
  lyrics: "",
  lyricsProvided: true,
  instrumental: true,
  durationSeconds: 120,
  loraId: "",
};

describe("buildGenerationRequest", () => {
  it("keeps free text out of the control bag (idea/style only)", () => {
    const b = buildGenerationRequest({ ...base, idea: "a rainy night", styles: "lofi" });
    expect(b.controls).not.toHaveProperty("description");
    expect(b.controls).not.toHaveProperty("styles");
    expect(b.song_idea).toBe("a rainy night");
    expect(b.style_prompt).toBe("lofi");
    expect(b.music_description).toContain("a rainy night");
    expect(b.music_description).toContain("lofi");
  });

  it("folds the singer into the caption for vocal tracks only", () => {
    const vocal = buildGenerationRequest({ ...base, instrumental: false, gender: "Female", lyrics: "la la", lyricsProvided: true });
    expect(vocal.music_description).toContain("female vocals");
    const instr = buildGenerationRequest({ ...base, instrumental: true, gender: "Female" });
    expect(instr.music_description).not.toContain("vocals");
  });

  it("preserves exact approved lyrics and reports real provenance", () => {
    const b = buildGenerationRequest({ ...base, instrumental: false, lyrics: "  Keep me\n[Chorus]\n  ", lyricsProvided: true });
    expect(b.lyrics).toBe("  Keep me\n[Chorus]\n  ");
    expect(b.lyrics_origin).toBe("human");
    const auto = buildGenerationRequest({ ...base, instrumental: false, lyrics: "written", lyricsProvided: false });
    expect(auto.lyrics_origin).toBe("frontend_llm");
  });

  it("omits lyrics for instrumental output", () => {
    const b = buildGenerationRequest({ ...base, instrumental: true, lyrics: "x" });
    expect(b).not.toHaveProperty("lyrics");
  });

  it("filters controls to the model's supported set (base-only shift dropped on turbo)", () => {
    const turbo = buildGenerationRequest({ ...base, shift: 3 });
    expect(turbo.controls).not.toHaveProperty("shift");
    const baseModel = buildGenerationRequest(
      { ...base, shift: 3 },
      { supportedControls: ["shift", "bpm"] },
    );
    expect(baseModel.controls).toHaveProperty("shift", 3);
  });

  it("emits supported numeric controls incl. time_signature and intentional shift:0", () => {
    const b = buildGenerationRequest(
      { ...base, bpm: "110", keyScale: "Amin", timeSignature: "6/8", language: "en", quality: 32, guidance: 7, variations: 3, durationSeconds: 210 },
      { supportedControls: ["bpm", "key_scale", "time_signature", "vocal_language", "inference_steps", "guidance_scale", "variations", "shift"] },
    );
    const c = b.controls as Record<string, unknown>;
    expect(c.bpm).toBe(110);
    expect(c.key_scale).toBe("Amin");
    expect(c.time_signature).toBe("6/8");
    expect(c.vocal_language).toBe("en");
    expect(c.inference_steps).toBe(32);
    expect(c.guidance_scale).toBe(7);
    expect(c.variations).toBe(3);
    expect(b.duration_seconds).toBe(210);
  });

  it("keeps a false-y-but-valid shift:0 when the model supports shift", () => {
    const b = buildGenerationRequest(
      { ...base, shift: 0 },
      { supportedControls: ["shift"] },
    );
    expect(b.controls).toHaveProperty("shift", 0);
  });

  it("falls back to title when caption is empty", () => {
    const b = buildGenerationRequest({ ...base, title: "Instrumental Cue" });
    expect(b.music_description).toBe("Instrumental Cue");
  });

  it("omits seed unless provided", () => {
    expect(buildGenerationRequest({ ...base })).not.toHaveProperty("seed");
    expect(buildGenerationRequest({ ...base, seed: 7 })).toHaveProperty("seed", 7);
  });

  it("adds source-conditioned fields for a cover, keeping controls clean", () => {
    const b = buildGenerationRequest({
      ...base,
      styles: "thrash metal",
      taskType: "cover",
      srcAssetId: "asset-123",
      audioCoverStrength: 0.7,
      coverNoiseStrength: 0.2,
    });
    expect(b.task_type).toBe("cover");
    expect(b.src_asset_id).toBe("asset-123");
    expect(b.audio_cover_strength).toBe(0.7);
    expect(b.cover_noise_strength).toBe(0.2);
    expect(b.style_prompt).toBe("thrash metal");
    expect(b.music_description).toContain("thrash metal");
    expect(b.controls).not.toHaveProperty("styles");
    expect(b.controls).not.toHaveProperty("description");
  });

  it("leaves task/source fields absent for a plain text2music request", () => {
    const b = buildGenerationRequest({ ...base, idea: "sunny" });
    expect(b).not.toHaveProperty("task_type");
    expect(b).not.toHaveProperty("src_asset_id");
  });
});
