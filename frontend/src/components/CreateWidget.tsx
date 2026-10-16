import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { api } from "../api";

interface JobAccepted {
  job_id: string;
}
interface JobDetail {
  status: string;
  stage?: string | null;
  error_code?: string | null;
  error_message?: string | null;
}
interface ArtifactItem {
  asset_id: string;
  role: string;
  mime: string;
  duration_seconds: number | null;
}
interface ArtifactsResp {
  artifacts: ArtifactItem[];
}
interface DownloadResp {
  url: string;
}

export default function CreateWidget() {
  const [desc, setDesc] = useState("A dreamy indie pop song about chasing a brighter tomorrow");
  const [duration, setDuration] = useState(30);
  const [instrumental, setInstrumental] = useState(true);
  const [jobId, setJobId] = useState<string | null>(null);
  const [error, setError] = useState("");

  const generate = useMutation({
    mutationFn: () =>
      api.post<JobAccepted>("/api/v1/jobs", {
        operation: "music.generate",
        model_id: "ace-step-1.5",
        music_description: desc,
        duration_seconds: duration,
        instrumental,
        outputs: ["mix_wav"],
      }),
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
    queryFn: () => api.get<ArtifactsResp>(`/api/v1/jobs/${jobId}/artifacts`),
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
  const busy = generate.isPending || (status && status !== "succeeded" && status !== "failed");

  return (
    <div className="card">
      <textarea rows={2} value={desc} onChange={(e) => setDesc(e.target.value)} />
      <div style={{ display: "flex", gap: 12, marginTop: 12, flexWrap: "wrap", alignItems: "center" }}>
        <label style={{ display: "flex", gap: 6, alignItems: "center", width: "auto" }}>
          <input style={{ width: 70 }} type="number" min={1} max={600} value={duration}
            onChange={(e) => setDuration(Number(e.target.value))} />
          sec
        </label>
        <label style={{ display: "flex", gap: 6, alignItems: "center", width: "auto" }}>
          <input style={{ width: "auto" }} type="checkbox" checked={instrumental}
            onChange={(e) => setInstrumental(e.target.checked)} />
          Instrumental
        </label>
        <button className="primary" disabled={!!busy} onClick={() => generate.mutate()}>
          {busy ? "Generating..." : "Generate"}
        </button>
        {error && <span style={{ color: "crimson" }}>{error}</span>}
        {status === "failed" && <span style={{ color: "crimson" }}>{job.data?.error_code}</span>}
      </div>
      {status && status !== "succeeded" && status !== "failed" && (
        <p style={{ color: "var(--muted)" }}>Status: {status}{job.data?.stage ? ` / ${job.data.stage}` : ""}</p>
      )}
      {urls.data &&
        artifacts.data?.artifacts
          .filter((a) => a.mime.startsWith("audio/"))
          .map((a) => (
            <div key={a.asset_id} style={{ marginTop: 12 }}>
              <audio controls src={urls.data[a.asset_id]} style={{ width: "100%" }} />
              <a href={urls.data[a.asset_id]} download style={{ marginLeft: 8 }}>
                WAV
              </a>
            </div>
          ))}
    </div>
  );
}
