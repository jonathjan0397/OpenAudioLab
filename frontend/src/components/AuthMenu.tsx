import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, AuthUser } from "../api";

export default function AuthMenu() {
  const qc = useQueryClient();
  const me = useQuery({
    queryKey: ["me"],
    queryFn: () => api.get<{ user: AuthUser }>("/api/v1/auth/me"),
    retry: false,
  });
  const [mode, setMode] = useState<"login" | "register" | null>(null);
  const [email, setEmail] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");

  const submit = useMutation({
    mutationFn: () =>
      mode === "register"
        ? api.post<{ user: AuthUser }>("/api/v1/auth/register", { email, username, password })
        : api.post<{ user: AuthUser }>("/api/v1/auth/login", { email, password }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["me"] });
      setMode(null);
      setError("");
    },
    onError: (e: Error) => setError(e.message),
  });

  const logout = useMutation({
    mutationFn: () => api.post("/api/v1/auth/logout"),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["me"] }),
  });

  if (me.data?.user) {
    return (
      <span style={{ display: "flex", gap: 10, alignItems: "center" }}>
        <span style={{ color: "var(--muted)" }}>
          {me.data.user.username} · {me.data.user.credits_balance} cr
        </span>
        <button className="primary" onClick={() => logout.mutate()}>
          Sign Out
        </button>
      </span>
    );
  }
  if (!mode) {
    return <button className="primary" onClick={() => setMode("login")}>Sign In</button>;
  }
  return (
    <span style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
      <input style={{ width: 170 }} placeholder="email" value={email} onChange={(e) => setEmail(e.target.value)} />
      {mode === "register" && (
        <input style={{ width: 110 }} placeholder="username" value={username} onChange={(e) => setUsername(e.target.value)} />
      )}
      <input
        style={{ width: 130 }}
        type="password"
        placeholder="password"
        value={password}
        onChange={(e) => setPassword(e.target.value)}
      />
      <button className="primary" onClick={() => submit.mutate()} disabled={submit.isPending}>
        {submit.isPending ? "..." : mode === "register" ? "Join" : "Go"}
      </button>
      <button onClick={() => setMode(mode === "login" ? "register" : "login")}>
        {mode === "login" ? "Join" : "Sign In"}
      </button>
      {error && <span style={{ color: "crimson", fontSize: 12 }}>{error}</span>}
    </span>
  );
}
