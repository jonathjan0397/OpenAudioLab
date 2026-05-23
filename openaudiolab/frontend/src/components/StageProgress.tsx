const stageIcons: Record<string, string> = {
  completed: "✓",
  running: "⏳",
  failed: "✗",
  skipped: "⊘",
  pending: "○",
};

export default function StageProgress({ stages }: { stages: { stage_name: string; status: string }[] }) {
  const stageLabels: Record<string, string> = {
    job_intake: "Job Intake",
    prompt_validation: "Prompt Validation",
    lyrics_generation_or_ingestion: "Lyrics Generation",
    lyrics_structure_validation: "Structure Validation",
    lyrics_reasoning: "Lyric Reasoning",
    lyrics_revision: "Lyric Revision",
    lyrics_humanization: "Lyric Humanization",
    composition_planning: "Composition Planning",
    audio_generation: "Audio Generation",
    daw_processing: "DAW Processing",
    effects_processing: "Effects Processing",
    mastering: "Mastering",
    preview_waveform_generation: "Waveform Generation",
    zip_export: "ZIP Export",
    storage_upload: "Storage Upload",
    signed_download_url: "Download URL",
    retention_cleanup: "Retention Cleanup",
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
      {stages.map((stage, i) => (
        <div key={i} style={{ display: "flex", alignItems: "center", gap: "8px", fontSize: "14px" }}>
          <span style={{ width: "20px", textAlign: "center", color: stage.status === "completed" ? "#27ae60" : stage.status === "running" ? "#3498db" : stage.status === "failed" ? "#e74c3c" : stage.status === "skipped" ? "#95a5a6" : "#ccc" }}>
            {stageIcons[stage.status] || "○"}
          </span>
          <span style={{ color: stage.status === "pending" ? "#999" : "#333" }}>
            {stageLabels[stage.stage_name] || stage.stage_name}
          </span>
        </div>
      ))}
    </div>
  );
}
