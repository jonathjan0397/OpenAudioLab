export default function AgentCard({ agent }: { agent: any }) {
  return (
    <div style={{ border: "1px solid #ddd", borderRadius: "8px", padding: "16px", background: "#fff" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "8px" }}>
        <strong>{agent.agent_name}</strong>
        <span style={{ fontSize: "12px", padding: "2px 8px", borderRadius: "12px", background: agent.status === "idle" ? "#27ae60" : agent.status === "busy" ? "#3498db" : "#e74c3c", color: "#fff" }}>
          {agent.status}
        </span>
      </div>
      <div style={{ fontSize: "13px", color: "#666", display: "grid", gridTemplateColumns: "1fr 1fr", gap: "4px" }}>
        <span>Mode: {agent.agent_mode}</span>
        <span>GPU: {agent.gpu_available ? agent.gpu_name : "None"}</span>
        <span>VRAM: {agent.vram_gb} GB</span>
        <span>CUDA: {agent.cuda_available ? "Yes" : "No"}</span>
        <span>Version: {agent.container_version}</span>
        <span>Draining: {agent.draining ? "Yes" : "No"}</span>
      </div>
      {agent.last_heartbeat_at && (
        <div style={{ fontSize: "11px", color: "#999", marginTop: "8px" }}>
          Last heartbeat: {new Date(agent.last_heartbeat_at).toLocaleString()}
        </div>
      )}
    </div>
  );
}
