import { useQuery } from "@tanstack/react-query";
import { api, AuthUser } from "../api";

export default function SettingsPage() {
  const me = useQuery({
    queryKey: ["me"],
    queryFn: () => api.get<{ user: AuthUser }>("/api/v1/auth/me"),
    retry: false,
  });
  return (
    <main className="page">
      <div className="section-head" style={{ marginTop: 10 }}>
        <h2>Settings</h2>
        <span className="sub">Account and preferences</span>
      </div>
      {me.data?.user ? (
        <div className="card" style={{ maxWidth: 460 }}>
          {[
            ["Email", me.data.user.email || "—"],
            ["Username", me.data.user.username],
            ["Credits", me.data.user.credits_balance.toLocaleString()],
          ].map(([k, v]) => (
            <div key={k} style={{ display: "flex", justifyContent: "space-between", padding: "10px 0", borderBottom: "1px solid var(--border)" }}>
              <span style={{ color: "var(--muted)" }}>{k}</span>
              <strong>{v}</strong>
            </div>
          ))}
          <p style={{ color: "var(--muted)", fontSize: 12, marginTop: 12 }}>
            Password change and theme preference are coming soon.
          </p>
        </div>
      ) : (
        <p style={{ color: "var(--muted)" }}>Sign in (top right) to manage your account.</p>
      )}
    </main>
  );
}
