export default function WorkerCard({ worker }: { worker: any }) {
  return (
    <div style={{ border: "1px solid #ddd", borderRadius: "8px", padding: "16px", background: "#fff" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "8px" }}>
        <strong>{worker.worker_name}</strong>
        <span style={{ fontSize: "12px", padding: "2px 8px", borderRadius: "12px", background: worker.status === "idle" ? "#27ae60" : worker.status === "busy" ? "#3498db" : "#e74c3c", color: "#fff" }}>
          {worker.status}
        </span>
      </div>
      <div style={{ fontSize: "13px", color: "#666", display: "grid", gridTemplateColumns: "1fr 1fr", gap: "4px" }}>
        <span>Mode: {worker.worker_mode}</span>
        <span>GPU: {worker.gpu_available ? worker.gpu_name : "None"}</span>
        <span>VRAM: {worker.vram_gb} GB</span>
        <span>CUDA: {worker.cuda_available ? "Yes" : "No"}</span>
        <span>Version: {worker.container_version}</span>
        <span>Draining: {worker.draining ? "Yes" : "No"}</span>
      </div>
      {worker.last_heartbeat_at && (
        <div style={{ fontSize: "11px", color: "#999", marginTop: "8px" }}>
          Last heartbeat: {new Date(worker.last_heartbeat_at).toLocaleString()}
        </div>
      )}
    </div>
  );
}
