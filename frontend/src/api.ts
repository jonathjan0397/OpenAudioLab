export const API = "";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API}${path}`, {
    credentials: "include",
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = (body as { error?: { code?: string; message?: string } }).error;
    throw new Error(error?.message || `${response.status}`);
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
