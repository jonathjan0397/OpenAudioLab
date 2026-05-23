import { useState } from "react";
import { useNavigate } from "react-router-dom";
import api from "../api/client";
import LyricsFormattingGuide from "../components/LyricsFormattingGuide";

export default function CreateJob() {
  const navigate = useNavigate();
  const [form, setForm] = useState({
    prompt: "",
    genre: "",
    mood: "",
    lyrics_mode: "ai",
    provided_lyrics: "",
    instrumental: false,
    duration_seconds: 15,
    vocal_mode: "male",
    quality: "draft",
    lyric_reasoning_mode: "balanced",
    dispatch_preference: "cpu_test",
    storage_retention_days: 7,
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const res = await api.post("/api/jobs", form);
      navigate(`/jobs/${res.data.id}`);
    } catch (err: any) {
      setError(err.response?.data?.detail || "Failed to create job");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ maxWidth: "700px" }}>
      <h2>Create Test Job</h2>
      {error && <div style={{ background: "#fee", color: "#c00", padding: "8px", borderRadius: "4px", marginBottom: "16px" }}>{error}</div>}
      <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: "16px", background: "#fff", padding: "24px", borderRadius: "8px", border: "1px solid #ddd" }}>
        <label>Prompt<textarea value={form.prompt} onChange={(e) => setForm({ ...form, prompt: e.target.value })} required rows={3} style={{ width: "100%", padding: "8px" }} placeholder="dark cinematic country rock song about rebuilding after collapse" /></label>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px" }}>
          <label>Genre<input type="text" value={form.genre} onChange={(e) => setForm({ ...form, genre: e.target.value })} style={{ width: "100%", padding: "8px" }} /></label>
          <label>Mood<input type="text" value={form.mood} onChange={(e) => setForm({ ...form, mood: e.target.value })} style={{ width: "100%", padding: "8px" }} /></label>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px" }}>
          <label>Lyrics Mode
            <select value={form.lyrics_mode} onChange={(e) => setForm({ ...form, lyrics_mode: e.target.value, instrumental: e.target.value === "instrumental" })} style={{ width: "100%", padding: "8px" }}>
              <option value="ai">AI Generated</option>
              <option value="provided">Custom (Provided)</option>
              <option value="hybrid">Hybrid</option>
              <option value="instrumental">Instrumental</option>
            </select>
          </label>
          <label>Dispatch Preference
            <select value={form.dispatch_preference} onChange={(e) => setForm({ ...form, dispatch_preference: e.target.value })} style={{ width: "100%", padding: "8px" }}>
              <option value="cpu_test">CPU Test</option>
              <option value="auto">Auto</option>
              <option value="local">Local</option>
            </select>
          </label>
        </div>
        {form.lyrics_mode === "provided" && (
          <div style={{ background: "#e8f5e9", padding: "12px", borderRadius: "4px", fontSize: "14px" }}>
            <strong>Custom lyrics will be used exactly as written.</strong> OpenAudiolab will not rewrite, humanize, or correct them automatically.
          </div>
        )}
        {form.lyrics_mode === "hybrid" && (
          <div style={{ background: "#fff3e0", padding: "12px", borderRadius: "4px", fontSize: "14px" }}>
            <strong>Hybrid mode may rewrite, expand, or restructure your submitted idea into complete lyrics.</strong>
          </div>
        )}
        {(form.lyrics_mode === "provided" || form.lyrics_mode === "hybrid") && (
          <div>
            <LyricsFormattingGuide />
            <label style={{ marginTop: "8px", display: "block" }}>Your Lyrics<textarea value={form.provided_lyrics} onChange={(e) => setForm({ ...form, provided_lyrics: e.target.value })} rows={10} style={{ width: "100%", padding: "8px", fontFamily: "monospace", fontSize: "13px" }} placeholder={`[Verse 1]\nWrite your first verse here\nKeep each sung line on its own line\n\n[Pre-Chorus]\nOptional build-up section\n\n[Chorus]\nMain hook goes here\nRepeatable and memorable works best\n\n[Verse 2]\nContinue the story or develop the idea\n\n[Bridge]\nOptional contrast or emotional turn\n\n[Outro]\nOptional ending line or refrain`} /></label>
          </div>
        )}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: "12px" }}>
          <label>Duration (seconds)<input type="number" value={form.duration_seconds} onChange={(e) => setForm({ ...form, duration_seconds: parseInt(e.target.value) })} min={5} max={600} style={{ width: "100%", padding: "8px" }} /></label>
          <label>Vocal Mode
            <select value={form.vocal_mode} onChange={(e) => setForm({ ...form, vocal_mode: e.target.value })} style={{ width: "100%", padding: "8px" }}>
              <option value="male">Male</option>
              <option value="female">Female</option>
              <option value="both">Both</option>
            </select>
          </label>
          <label>Quality
            <select value={form.quality} onChange={(e) => setForm({ ...form, quality: e.target.value })} style={{ width: "100%", padding: "8px" }}>
              <option value="draft">Draft</option>
              <option value="standard">Standard</option>
              <option value="high">High</option>
              <option value="studio">Studio</option>
            </select>
          </label>
        </div>
        <label><input type="checkbox" checked={form.instrumental} onChange={(e) => setForm({ ...form, instrumental: e.target.checked })} /> Instrumental (no vocals)</label>
        <button type="submit" disabled={loading} style={{ background: "#27ae60", color: "#fff", border: "none", padding: "12px", borderRadius: "4px", cursor: "pointer", fontSize: "16px" }}>
          {loading ? "Creating..." : "Submit Job"}
        </button>
      </form>
    </div>
  );
}
