export const JOB_STATES = [
  "created",
  "queued",
  "waiting_for_worker",
  "provisioning_worker",
  "assigned",
  "running",
  "stage_completed",
  "uploading_results",
  "completed",
  "failed",
  "cancelled",
  "expired",
] as const;

export const STAGE_STATES = [
  "pending",
  "running",
  "completed",
  "failed",
  "skipped",
] as const;

export const JOB_STATE_COLORS: Record<string, string> = {
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
