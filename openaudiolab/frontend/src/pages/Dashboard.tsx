import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import api from "../api/client";

export default function Dashboard() {
  const [system, setSystem] = useState<any>(null);
  const [jobs, setJobs] = useState<any[]>([]);

  useEffect(() => {
    api.get("/api/system/status").then((r) => setSystem(r.data));
    api.get("/api/jobs?limit=10").then((r) => setJobs(r.data));
  }, []);

  const statusCounts = jobs.reduce((acc: any, job: any) => {
    acc[job.status] = (acc[job.status] || 0) + 1;
    return acc;
  }, {});

  return (
    <div>
      <h2>Dashboard</h2>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))", gap: "16px", marginBottom: "24px" }}>
        <div style={{ background: "#fff", padding: "16px", borderRadius: "8px", border: "1px solid #ddd" }}>
          <div style={{ fontSize: "28px", fontWeight: "bold" }}>{jobs.length}</div>
          <div style={{ color: "#666" }}>Total Jobs</div>
        </div>
        <div style={{ background: "#fff", padding: "16px", borderRadius: "8px", border: "1px solid #ddd" }}>
          <div style={{ fontSize: "28px", fontWeight: "bold", color: "#3498db" }}>{statusCounts.running || 0}</div>
          <div style={{ color: "#666" }}>Running</div>
        </div>
        <div style={{ background: "#fff", padding: "16px", borderRadius: "8px", border: "1px solid #ddd" }}>
          <div style={{ fontSize: "28px", fontWeight: "bold", color: "#27ae60" }}>{statusCounts.completed || 0}</div>
          <div style={{ color: "#666" }}>Completed</div>
        </div>
        <div style={{ background: "#fff", padding: "16px", borderRadius: "8px", border: "1px solid #ddd" }}>
          <div style={{ fontSize: "28px", fontWeight: "bold", color: "#e74c3c" }}>{statusCounts.failed || 0}</div>
          <div style={{ color: "#666" }}>Failed</div>
        </div>
      </div>
      {system && (
        <div style={{ background: "#fff", padding: "16px", borderRadius: "8px", border: "1px solid #ddd", marginBottom: "24px" }}>
          <h3 style={{ marginTop: 0 }}>System Status</h3>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "8px", fontSize: "14px" }}>
            <span>Backend: {system.backend_online ? "Online" : "Offline"}</span>
            <span>Storage: {system.storage_provider}</span>
            <span>GPU: {system.local_gpu_status}</span>
            <span>Agents: {system.active_agents} active / {system.total_agents} total</span>
          </div>
        </div>
      )}
      <Link to="/jobs/new" style={{ display: "inline-block", background: "#27ae60", color: "#fff", padding: "10px 24px", borderRadius: "4px", textDecoration: "none" }}>Create Test Job</Link>
    </div>
  );
}
