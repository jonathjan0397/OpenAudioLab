export const API = "";

// Typed, safe error envelope mirroring the backend contract:
// {"error": {"code", "message", "request_id", "details"}}.
// It never carries the request body, tokens, or internal paths.
export interface ApiErrorDetails {
  unknown_controls?: string[];
  supported_controls?: string[];
  [key: string]: unknown;
}

export class ApiError extends Error {
  code: string;
  requestId?: string;
  details: ApiErrorDetails;
  status: number;

  constructor(
    message: string,
    opts: { code?: string; status?: number; requestId?: string; details?: ApiErrorDetails } = {},
  ) {
    super(message);
    this.name = "ApiError";
    this.code = opts.code ?? "UNKNOWN";
    this.status = opts.status ?? 0;
    this.requestId = opts.requestId;
    this.details = opts.details ?? {};
  }

  // Human-readable, actionable hint for the control-capability rejection.
  controlHint(): string | null {
    const unknown = this.details.unknown_controls;
    if (!unknown || unknown.length === 0) return null;
    const supported = this.details.supported_controls ?? [];
    const supportedText = supported.length ? ` Supported: ${supported.join(", ")}.` : "";
    return `These settings aren't available for this model and were not applied: ${unknown.join(", ")}.${supportedText}`;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API}${path}`, {
    credentials: "include",
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const err = (body as { error?: { code?: string; message?: string; request_id?: string; details?: ApiErrorDetails } }).error;
    throw new ApiError(err?.message || `${response.status}`, {
      code: err?.code,
      status: response.status,
      requestId: err?.request_id,
      details: err?.details,
    });
  }
  return body as T;
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, data?: unknown, headers?: Record<string, string>) =>
    request<T>(path, { method: "POST", body: data === undefined ? undefined : JSON.stringify(data), headers }),
  put: <T>(path: string, data?: unknown) =>
    request<T>(path, { method: "PUT", body: data === undefined ? undefined : JSON.stringify(data) }),
  patch: <T>(path: string, data?: unknown, headers?: Record<string, string>) =>
    request<T>(path, { method: "PATCH", body: data === undefined ? undefined : JSON.stringify(data), headers }),
  del: <T>(path: string) => request<T>(path, { method: "DELETE" }),
  delete: <T>(path: string) => request<T>(path, { method: "DELETE" }),
};

export interface SiteInfo {
  site_name: string;
  template: string;
  operator?: string;
  support_url?: string;
  policy_version?: string;
}

export interface AuthUser {
  id: string;
  email: string;
  username: string;
  role: string;
  state: string;
  plan: string;
  credits_balance: number;
  stripe_customer_id?: string | null;
  stripe_subscription_id?: string | null;
  subscription_status?: string | null;
  cancel_at_period_end?: boolean;
  current_period_end?: string | null;
  email_verified_at?: string | null;
  avatar_key?: string | null;
  bio?: string | null;
}

export interface GuestAllowance {
  guest_id: string;
  date: string;
  used: number;
  limit: number;
  remaining: number;
  reset_at: string;
  policy_accepted: boolean;
  policy_version: string | null;
  max_duration_seconds: number;
  claimed: boolean;
}

export interface PolicyPayload {
  version: string;
  operator: string;
  support_url: string;
  documents: { id: string; name: string; version: string }[];
}
