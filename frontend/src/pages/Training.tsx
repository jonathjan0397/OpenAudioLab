import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { Progress, StatusPill, humanizeStage } from "../components/ui";

interface VoiceJob {
  job_id: string;
  operation: string;
  status: string;
  stage: string | null;
  progress: number | null;
  error_code: string | null;
  created_at: string | null;
}

const OP_LABEL: Record<string, string> = {
  "voice.analyze": "Voice analysis",
  "voice.train": "Voice training",
  "voice.validate": "Voice validation",
};

export default function TrainingPage() {
  const runs = useQuery({
    queryKey: ["my-trainings"],
    queryFn: () => api.get<{ trainings: VoiceJob[] }>("/api/v1/trainings"),
    retry: false,
    refetchInterval: 10000,
  });
  return (
    <main className="page">
      <div className="section-head" style={{ marginTop: 10 }}>
        <h2>Training</h2>
        <span className="sub">UAIS voice jobs for your artists</span>
      </div>
      <div className="card" style={{ maxWidth: 640 }}>
        {(runs.data?.trainings || []).map((t) => (
          <div key={t.job_id} style={{ marginBottom: 14 }}>
            <div style={{ display: "flex", justifyContent: "space-between", fontSize: 14, marginBottom: 4 }}>
              <strong>{OP_LABEL[t.operation] || t.operation}</strong>
              <StatusPill status={t.status} />
            </div>
            <div style={{ fontSize: 12, color: "var(--muted)", marginBottom: 4 }}>
              {humanizeStage(t.stage) || t.status}
              {t.progress != null ? ` · ${Math.round(t.progress * 100)}%` : ""}
              {t.error_code ? ` · ${t.error_code}` : ""}
            </div>
            <Progress value={t.progress ?? (t.status === "succeeded" ? 1 : null)} />
          </div>
        ))}
        {(runs.data?.trainings || []).length === 0 && (
          <p style={{ color: "var(--muted)", fontSize: 13 }}>
            No voice jobs yet. Build a voice dataset in the{" "}
            <Link to="/artists">Voice Studio</Link>.
          </p>
        )}
      </div>
    </main>
  );
}
