import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import api from "../api/client";
import JobStatusBadge from "../components/JobStatusBadge";
import StageProgress from "../components/StageProgress";

export default function JobDetail() {
  const { jobId } = useParams();
  const [job, setJob] = useState<any>(null);
  const [logs, setLogs] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchJob = () => {
      api.get(`/api/jobs/${jobId}`).then((r) => setJob(r.data));
      api.get(`/api/jobs/${jobId}/logs`).then((r) => setLogs(r.data));
    };
    fetchJob();
    setLoading(false);
    const interval = setInterval(fetchJob, 3000);
    return () => clearInterval(interval);
  }, [jobId]);

  if (loading) return <div>Loading...</div>;
  if (!job) return <div>Job not found</div>;

  return (
    <div style={{ maxWidth: "800px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "16px" }}>
        <h2 style={{ margin: 0 }}>Job Progress</h2>
        <JobStatusBadge status={job.status} />
      </div>
      <div style={{ background: "#fff", padding: "16px", borderRadius: "8px", border: "1px solid #ddd", marginBottom: "16px" }}>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "8px", fontSize: "14px", marginBottom: "12px" }}>
          <span><strong>Job ID:</strong> {job.id}</span>
          <span><strong>Created:</strong> {new Date(job.created_at).toLocaleString()}</span>
          <span><strong>Prompt:</strong> {job.prompt}</span>
          <span><strong>Lyrics Mode:</strong> {job.lyrics_mode}</span>
          <span><strong>Duration:</strong> {job.duration_seconds}s</span>
          <span><strong>Quality:</strong> {job.quality}</span>
        </div>
        <h3 style={{ fontSize: "16px", marginTop: "16px" }}>Pipeline Stages</h3>
        <StageProgress stages={job.stages} />
      </div>
      {job.status === "completed" && (
        <div style={{ background: "#fff", padding: "16px", borderRadius: "8px", border: "1px solid #ddd", marginBottom: "16px" }}>
          <h3 style={{ fontSize: "16px", marginTop: 0 }}>Download</h3>
          <button onClick={() => api.get(`/api/jobs/${jobId}/download`).then((r) => window.open(r.data.download_url, "_blank"))} style={{ background: "#27ae60", color: "#fff", border: "none", padding: "10px 24px", borderRadius: "4px", cursor: "pointer" }}>
            Download ZIP
          </button>
        </div>
      )}
      {job.status === "failed" && (
        <div style={{ background: "#fee", padding: "16px", borderRadius: "8px", border: "1px solid #fcc", marginBottom: "16px" }}>
          <strong>Failed:</strong> {job.error_message}
        </div>
      )}
      <div style={{ background: "#fff", padding: "16px", borderRadius: "8px", border: "1px solid #ddd" }}>
        <h3 style={{ fontSize: "16px", marginTop: 0 }}>Logs</h3>
        <div style={{ maxHeight: "300px", overflowY: "auto", fontFamily: "monospace", fontSize: "12px" }}>
          {logs.map((log, i) => (
            <div key={i} style={{ padding: "2px 0", borderBottom: "1px solid #f0f0f0" }}>
              [{log.timestamp?.slice(0, 19)}] {log.stage}: {log.message}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
