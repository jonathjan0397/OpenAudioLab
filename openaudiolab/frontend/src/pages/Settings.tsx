import { useEffect, useState } from "react";
import api from "../api/client";

export default function Settings() {
  const [settings, setSettings] = useState<any>({});

  useEffect(() => {
    api.get("/api/settings").then((r) => setSettings(r.data));
  }, []);

  return (
    <div>
      <h2>Settings</h2>
      <div style={{ background: "#fff", padding: "24px", borderRadius: "8px", border: "1px solid #ddd" }}>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px", fontSize: "14px" }}>
          <span>Default Retention Days: <strong>{settings.default_retention_days ?? 7}</strong></span>
          <span>Storage Provider: <strong>{settings.storage_provider ?? "local"}</strong></span>
          <span>CPU Test Mode: <strong>{settings.enable_cpu_test_mode ? "Enabled" : "Disabled"}</strong></span>
          <span>Cloud Agents: <strong>{settings.enable_cloud_agents ? "Enabled" : "Disabled"}</strong></span>
          <span>Lyric Reasoning Mode: <strong>{settings.default_lyric_reasoning_mode ?? "balanced"}</strong></span>
          <span>Max Revision Attempts: <strong>{settings.max_lyric_revision_attempts ?? 3}</strong></span>
          <span>Max Job Duration: <strong>{settings.max_job_duration ?? 600}s</strong></span>
          <span>Agent Token: <strong>{settings.agent_registration_token}</strong></span>
        </div>
        <p style={{ marginTop: "16px", color: "#999", fontSize: "13px" }}>Settings management is a placeholder in this version. Use the API to update settings.</p>
      </div>
    </div>
  );
}
