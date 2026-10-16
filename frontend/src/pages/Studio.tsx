import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, AuthUser } from "../api";
import CreateWidget from "../components/CreateWidget";

interface Track {
  asset_id: string;
  title: string | null;
  shared: boolean;
  favorite: boolean;
  duration_seconds: number | null;
  created_at: string | null;
  expired: boolean;
  url: string;
}
interface JobRow {
  job_id: string;
  status: string;
  stage?: string | null;
  created_at?: string | null;
}

function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="card" style={{ flex: "1 1 140px" }}>
      <div style={{ color: "var(--muted)", fontSize: 13 }}>{label}</div>
      <div style={{ fontSize: 26, fontWeight: 700 }}>{value}</div>
    </div>
  );
}

export default function StudioPage() {
  const qc = useQueryClient();
  const me = useQuery({
    queryKey: ["me"],
    queryFn: () => api.get<{ user: AuthUser }>("/api/v1/auth/me"),
    retry: false,
  });
  const tracks = useQuery({
    queryKey: ["my-tracks"],
    queryFn: () => api.get<{ tracks: Track[] }>("/api/v1/tracks?limit=50"),
    enabled: !!me.data?.user,
  });
  const credits = useQuery({
    queryKey: ["credits"],
    queryFn: () => api.get<{ balance: number | null }>("/api/v1/credits"),
    enabled: !!me.data?.user,
  });
  const jobs = useQuery({
    queryKey: ["my-jobs"],
    queryFn: () => api.get<{ jobs: JobRow[] }>("/api/v1/jobs?limit=20"),
    enabled: !!me.data?.user,
    refetchInterval: 5000,
  });
  const [renaming, setRenaming] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");

  const toggle = useMutation({
    mutationFn: (id: string) => api.post(`/api/v1/artifacts/${id}/favorite`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["my-tracks"] }),
  });
  const share = useMutation({
    mutationFn: ({ id, shared }: { id: string; shared: boolean }) =>
      api.patch(`/api/v1/artifacts/${id}`, { shared }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["my-tracks"] }),
  });
  const rename = useMutation({
    mutationFn: ({ id, title }: { id: string; title: string }) =>
      api.patch(`/api/v1/artifacts/${id}`, { title }),
    onSuccess: () => {
      setRenaming(null);
      qc.invalidateQueries({ queryKey: ["my-tracks"] });
    },
  });

  if (!me.data?.user) {
    return (
      <main className="page">
        <h1>My Studio</h1>
        <p style={{ color: "var(--muted)" }}>Sign in (top right) to see your studio.</p>
      </main>
    );
  }

  const active = (jobs.data?.jobs || []).filter((j) =>
    ["queued", "waiting_for_worker", "running"].includes(j.status)
  );

  return (
    <main className="page" style={{ display: "grid", gap: 24 }}>
      <h1>My Studio</h1>
      <div style={{ display: "flex", gap: 14, flexWrap: "wrap" }}>
        <Stat label="Tracks Created" value={tracks.data?.tracks.length ?? 0} />
        <Stat label="Credits Remaining" value={credits.data?.balance ?? "-"} />
        <Stat label="Active Jobs" value={active.length} />
      </div>
      <CreateWidget />
      <section>
        <h2>My Tracks</h2>
        {(tracks.data?.tracks || []).map((t) => (
          <div key={t.asset_id} className="card" style={{ marginBottom: 10, display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
            <div style={{ flex: "1 1 220px" }}>
              {renaming === t.asset_id ? (
                <span style={{ display: "flex", gap: 6 }}>
                  <input value={renameValue} onChange={(e) => setRenameValue(e.target.value)} />
                  <button className="primary" onClick={() => rename.mutate({ id: t.asset_id, title: renameValue })}>
                    OK
                  </button>
                </span>
              ) : (
                <strong
                  style={{ cursor: "pointer" }}
                  onClick={() => {
                    setRenaming(t.asset_id);
                    setRenameValue(t.title || "");
                  }}
                >
                  {t.title || "Untitled (click to name)"}
                </strong>
              )}
              <div style={{ color: "var(--muted)", fontSize: 12 }}>
                {t.duration_seconds ? `${Math.round(t.duration_seconds)}s` : ""} · {t.created_at?.slice(0, 10)}
              </div>
            </div>
            <audio controls src={t.url} style={{ flex: "2 1 300px" }} />
            <button onClick={() => toggle.mutate(t.asset_id)}>{t.favorite ? "♥" : "♡"}</button>
            <button onClick={() => share.mutate({ id: t.asset_id, shared: !t.shared })}>
              {t.shared ? "Shared" : "Share"}
            </button>
            <a href={t.url} download>WAV</a>
          </div>
        ))}
        {tracks.data?.tracks.length === 0 && <p style={{ color: "var(--muted)" }}>No tracks yet.</p>}
      </section>
      <section>
        <h2>Generation Queue</h2>
        {active.length === 0 && <p style={{ color: "var(--muted)" }}>Nothing running.</p>}
        {active.map((j) => (
          <div key={j.job_id} className="card" style={{ marginBottom: 8 }}>
            {j.job_id.slice(0, 8)} — {j.status}
            {j.stage ? ` / ${j.stage}` : ""}
          </div>
        ))}
      </section>
    </main>
  );
}
