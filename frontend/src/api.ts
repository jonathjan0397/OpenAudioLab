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
  patch: <T>(path: string, data?: unknown) =>
    request<T>(path, { method: "PATCH", body: data === undefined ? undefined : JSON.stringify(data) }),
  del: <T>(path: string) => request<T>(path, { method: "DELETE" }),
};

export interface SiteInfo {
  site_name: string;
  template: string;
}

export interface AuthUser {
  id: string;
  email: string;
  username: string;
  role: string;
  state: string;
  credits_balance: number;
}
