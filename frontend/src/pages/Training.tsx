import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { Progress, StatusPill } from "../components/ui";

interface Training {
  run_id: string;
  job_id: string;
  status: string;
  stage: string | null;
  progress: number | null;
  hardware: string | null;
  created_at: string | null;
}

export default function TrainingPage() {
  const runs = useQuery({
    queryKey: ["my-trainings"],
    queryFn: () => api.get<{ trainings: Training[] }>("/api/v1/trainings"),
    retry: false,
  });
  return (
    <main className="page">
      <div className="section-head" style={{ marginTop: 10 }}>
        <h2>Training</h2>
        <span className="sub">Teach OpenAudioLab your sound</span>
      </div>
      <div className="card" style={{ maxWidth: 640 }}>
        {(runs.data?.trainings || []).map((t) => (
          <div key={t.run_id} style={{ marginBottom: 14 }}>
            <div style={{ display: "flex", justifyContent: "space-between", fontSize: 14, marginBottom: 4 }}>
              <strong>{t.run_id.slice(0, 8)}</strong>
              <StatusPill status={t.status} />
            </div>
            <div style={{ fontSize: 12, color: "var(--muted)", marginBottom: 4 }}>
              {t.stage ? `${t.stage}…` : t.status}
              {t.progress != null ? ` · ${Math.round(t.progress * 100)}%` : ""}
              {t.hardware ? ` · ${t.hardware}` : ""}
            </div>
            <Progress value={t.progress ?? (t.status === "succeeded" ? 1 : 0)} />
          </div>
        ))}
        {(runs.data?.trainings || []).length === 0 && (
          <p style={{ color: "var(--muted)", fontSize: 13 }}>
            No training runs yet. Upload a dataset and start one from the API or /lab.
          </p>
        )}
      </div>
    </main>
  );
}
