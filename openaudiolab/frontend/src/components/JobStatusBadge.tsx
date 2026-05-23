export default function JobStatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    created: "#3498db",
    queued: "#f39c12",
    waiting_for_worker: "#f39c12",
    assigned: "#9b59b6",
    running: "#3498db",
    stage_completed: "#3498db",
    uploading_results: "#9b59b6",
    completed: "#27ae60",
    failed: "#e74c3c",
    cancelled: "#95a5a6",
    expired: "#95a5a6",
  };
  const color = colors[status] || "#95a5a6";
  return (
    <span style={{ background: color, color: "#fff", padding: "2px 10px", borderRadius: "12px", fontSize: "12px", textTransform: "capitalize" }}>
      {status.replace(/_/g, " ")}
    </span>
  );
}
