import { useEffect, useState } from "react";
import api from "../api/client";

export default function SystemStatus() {
  const [system, setSystem] = useState<any>(null);

  useEffect(() => {
    api.get("/api/system/status").then((r) => setSystem(r.data));
  }, []);

  if (!system) return <div>Loading...</div>;

  return (
    <div>
      <h2>System Status</h2>
      <div style={{ background: "#fff", padding: "24px", borderRadius: "8px", border: "1px solid #ddd" }}>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px", fontSize: "14px" }}>
          <span>Backend: <strong>{system.backend_online ? "Online" : "Offline"}</strong></span>
          <span>Database: <strong>{system.database_online ? "Online" : "Offline"}</strong></span>
          <span>Redis: <strong>{system.redis_online ? "Online" : "Offline"}</strong></span>
          <span>Storage: <strong>{system.storage_online ? "Online" : "Offline"}</strong></span>
          <span>Storage Provider: <strong>{system.storage_provider}</strong></span>
          <span>Local GPU: <strong>{system.local_gpu_status}</strong></span>
          <span>Cloud Providers: <strong>{system.configured_cloud_providers.join(", ") || "None"}</strong></span>
          <span>Default Retention: <strong>{system.default_retention_days} days</strong></span>
          <span>Active Agents: <strong>{system.active_agents}</strong></span>
          <span>Total Agents: <strong>{system.total_agents}</strong></span>
          <span>Setup: <strong>{system.setup_status?.setup_completed ? "Completed" : "Not completed"}</strong></span>
        </div>
        {system.security_warnings && system.security_warnings.length > 0 && (
          <div style={{ marginTop: "16px", background: "#fff3e0", padding: "12px", borderRadius: "4px" }}>
            <strong>Security Warnings:</strong>
            <ul>{system.security_warnings.map((w: string, i: number) => <li key={i}>{w}</li>)}</ul>
          </div>
        )}
      </div>
    </div>
  );
}
