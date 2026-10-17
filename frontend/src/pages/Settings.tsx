import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, AuthUser } from "../api";

export default function SettingsPage() {
  const qc = useQueryClient();
  const me = useQuery({
    queryKey: ["me"],
    queryFn: () => api.get<{ user: AuthUser }>("/api/v1/auth/me"),
    retry: false,
  });
  const user = me.data?.user;

  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [bio, setBio] = useState("");
  const [saved, setSaved] = useState("");
  const [curPw, setCurPw] = useState("");
  const [newPw, setNewPw] = useState("");
  const [confirmPw, setConfirmPw] = useState("");
  const [pwMsg, setPwMsg] = useState("");
  const [avatarErr, setAvatarErr] = useState("");

  useEffect(() => {
    if (user) {
      setUsername(user.username);
      setEmail(user.email);
      setBio(user.bio || "");
    }
  }, [user?.id]);

  const save = useMutation({
    mutationFn: () => api.patch<{ user: AuthUser }>("/api/v1/auth/me", { username, email, bio }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["me"] });
      setSaved("Saved.");
    },
    onError: (e: Error) => setSaved(e.message),
  });

  const changePw = useMutation({
    mutationFn: () => api.post("/api/v1/auth/password", { current_password: curPw, new_password: newPw }),
    onSuccess: () => {
      setCurPw("");
      setNewPw("");
      setConfirmPw("");
      setPwMsg("Password updated.");
    },
    onError: (e: Error) => setPwMsg(e.message),
  });

  const uploadAvatar = useMutation({
    mutationFn: (file: File) => {
      const fd = new FormData();
      fd.append("file", file);
      return fetch(`/api/v1/auth/avatar`, { method: "POST", body: fd, credentials: "include" })
        .then(async (r) => {
          const body = await r.json().catch(() => ({}));
          if (!r.ok) throw new Error(body?.error?.message || `${r.status}`);
          return body as { user: AuthUser };
        });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["me"] });
      setAvatarErr("");
    },
    onError: (e: Error) => setAvatarErr(e.message),
  });

  if (!user) {
    return (
      <main className="page">
        <div className="section-head" style={{ marginTop: 10 }}>
          <h2>Profile</h2>
        </div>
        <p style={{ color: "var(--muted)" }}>Sign in (top right) to manage your account.</p>
      </main>
    );
  }

  return (
    <main className="page">
      <div className="section-head" style={{ marginTop: 10 }}>
        <h2>Profile</h2>
        <span className="sub">Account and preferences</span>
      </div>
      <div className="profile-grid">
        <div className="card">
          <div className="card-header"><h3>Profile</h3></div>
          <div className="profile-avatar-row">
            {user.avatar_key ? (
              <img className="avatar round lg" src={`/api/v1/auth/avatar/${user.id}?t=${me.dataUpdatedAt}`} alt="" />
            ) : (
              <span className="avatar round lg">{user.username.slice(0, 2).toUpperCase()}</span>
            )}
            <label className="btn btn-sm">
              {uploadAvatar.isPending ? "Uploading…" : "Upload avatar"}
              <input
                type="file"
                accept="image/png,image/jpeg,image/webp"
                hidden
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) uploadAvatar.mutate(f);
                  e.target.value = "";
                }}
              />
            </label>
            <span style={{ color: "var(--muted)", fontSize: 12 }}>PNG/JPG/WebP ≤ 2 MB</span>
          </div>
          {avatarErr && <p className="form-error">{avatarErr}</p>}
          <div className="field">
            <label>Username</label>
            <input value={username} onChange={(e) => setUsername(e.target.value)} />
          </div>
          <div className="field">
            <label>Email</label>
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
          </div>
          <div className="field">
            <label>Bio</label>
            <textarea rows={3} maxLength={500} value={bio} onChange={(e) => setBio(e.target.value)} placeholder="Tell listeners who you are…" />
          </div>
          <button className="btn btn-primary" onClick={() => { setSaved(""); save.mutate(); }} disabled={save.isPending}>
            {save.isPending ? "Saving…" : "Save"}
          </button>
          {saved && <span className="form-note"> {saved}</span>}
        </div>
        <div className="card">
          <div className="card-header"><h3>Password</h3></div>
          <div className="field">
            <label>Current password</label>
            <input type="password" value={curPw} onChange={(e) => setCurPw(e.target.value)} />
          </div>
          <div className="field">
            <label>New password</label>
            <input type="password" value={newPw} onChange={(e) => setNewPw(e.target.value)} />
          </div>
          <div className="field">
            <label>Confirm new password</label>
            <input type="password" value={confirmPw} onChange={(e) => setConfirmPw(e.target.value)} />
          </div>
          <button
            className="btn"
            disabled={changePw.isPending || !curPw || newPw.length < 8}
            onClick={() => {
              if (newPw !== confirmPw) {
                setPwMsg("New passwords do not match.");
                return;
              }
              setPwMsg("");
              changePw.mutate();
            }}
          >
            {changePw.isPending ? "Updating…" : "Change password"}
          </button>
          {pwMsg && <p className="form-note">{pwMsg}</p>}
          <div className="card-header" style={{ marginTop: 18 }}><h3>Plan</h3></div>
          <p style={{ margin: "4px 0" }}>
            <strong>{user.plan}</strong> · {user.credits_balance.toLocaleString()} credits
          </p>
          <Link className="link" to="/pricing">Manage plan →</Link>
        </div>
      </div>
    </main>
  );
}
