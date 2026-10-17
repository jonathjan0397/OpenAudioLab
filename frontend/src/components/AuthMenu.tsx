import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, AuthUser } from "../api";

export default function AuthMenu() {
  const qc = useQueryClient();
  const me = useQuery({
    queryKey: ["me"],
    queryFn: () => api.get<{ user: AuthUser }>("/api/v1/auth/me"),
    retry: false,
  });
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const wrapRef = useRef<HTMLSpanElement>(null);
  const user = me.data?.user;

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);

  const submit = useMutation({
    mutationFn: () =>
      mode === "register"
        ? api.post<{ user: AuthUser }>("/api/v1/auth/register", { email, username, password })
        : api.post<{ user: AuthUser }>("/api/v1/auth/login", { email, password }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["me"] });
      setOpen(false);
      setError("");
      setPassword("");
    },
    onError: (e: Error) => setError(e.message),
  });

  const logout = useMutation({
    mutationFn: () => api.post("/api/v1/auth/logout"),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["me"] });
      setOpen(false);
    },
  });

  return (
    <span className="auth-wrap" ref={wrapRef}>
      {user ? (
        <button className="auth-trigger" onClick={() => setOpen((o) => !o)}>
          {user.avatar_key ? (
            <img className="avatar round" src={`/api/v1/auth/avatar/${user.id}?t=${me.dataUpdatedAt}`} alt="" />
          ) : (
            <span className="avatar">{user.username.slice(0, 2).toUpperCase()}</span>
          )}
          <span className="auth-credits">{user.credits_balance.toLocaleString()} cr</span>
          <span className="caret" aria-hidden>▾</span>
        </button>
      ) : (
        <button className="btn btn-ghost btn-sm" onClick={() => setOpen((o) => !o)}>Sign In</button>
      )}
      {open && user && (
        <div className="card auth-menu">
          <div className="auth-menu-head">
            <strong>{user.username}</strong>
            <span className="sub">{user.plan} plan · {user.credits_balance.toLocaleString()} cr</span>
          </div>
          <Link to="/settings" className="auth-menu-item" onClick={() => setOpen(false)}>Profile</Link>
          {user.role === "admin" && (
            <Link to="/admin" className="auth-menu-item" onClick={() => setOpen(false)}>Admin</Link>
          )}
          <button className="auth-menu-item" onClick={() => logout.mutate()}>Sign Out</button>
        </div>
      )}
      {open && !user && (
        <div className="card auth-menu">
          <div className="auth-tabs">
            <button className={mode === "login" ? "on" : ""} onClick={() => setMode("login")}>Sign In</button>
            <button className={mode === "register" ? "on" : ""} onClick={() => setMode("register")}>Join</button>
          </div>
          <input placeholder="email" value={email} onChange={(e) => setEmail(e.target.value)} />
          {mode === "register" && (
            <input placeholder="username" value={username} onChange={(e) => setUsername(e.target.value)} />
          )}
          <input
            type="password"
            placeholder="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && submit.mutate()}
          />
          {error && <span className="auth-error">{error}</span>}
          <button className="btn btn-primary" onClick={() => submit.mutate()} disabled={submit.isPending}>
            {submit.isPending ? "..." : mode === "register" ? "Join" : "Sign In"}
          </button>
        </div>
      )}
    </span>
  );
}
