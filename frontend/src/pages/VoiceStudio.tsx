import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, api } from "../api";
import { Progress, StatusPill } from "../components/ui";

interface ArtistRow {
  profile_id: string;
  name: string;
  slug: string | null;
  default_voice_profile_id: string | null;
}

interface Recording {
  recording_id: string;
  filename: string;
  duration_seconds: number | null;
  qc: { verdict?: string; warnings?: string[] } | null;
  state: string;
}

interface DatasetResp {
  dataset_id: string;
  latest_version_number: number;
  recordings: Recording[];
  latest_version: { version_number: number; report: { warnings?: string[] } } | null;
}

interface Adapter {
  adapter_id: string;
  model_selection: string;
  state: string;
  training_job_id: string | null;
  validation: { similarity?: number; threshold?: number; passed?: boolean } | null;
  last_validated_at: string | null;
}

interface VoiceStatus {
  dataset: { dataset_id: string; latest_version_number: number } | null;
  voice_profiles: { voice_profile_id: string; version_number: number; status: string; is_default: boolean }[];
  adapters: Adapter[];
  analyses: { analysis_id: string; embedding_model: string; input_type: string; created_at: string }[];
  recent_jobs: { job_id: string; operation: string; status: string; stage: string | null; progress: number | null }[];
}

interface CompatRow {
  model_selection: string;
  state: string;
  adapter_id: string | null;
  detail?: string;
}

interface Capability {
  model_selection: string;
  training_recipe: string | null;
  adapter_load_verified: boolean;
  limitations: string[];
}

const STATE_LABEL_ADAPTER: Record<string, string> = {
  validated: "validated", ready: "ready (unvalidated)", stale: "stale", training: "training…", failed: "failed",
};

const STATE_LABEL: Record<string, string> = {
  NATIVE_ADAPTER_READY: "native adapter ready",
  ADAPTER_VALIDATION_REQUIRED: "trained — validation required",
  REFERENCE_CONDITIONING_AVAILABLE: "reference conditioning only",
  ADAPTER_TRAINING_REQUIRED: "adapter training required",
  PREPARING: "preparing…",
  UNSUPPORTED: "unsupported",
  FAILED: "failed",
};

export default function VoiceStudioPage() {
  const qc = useQueryClient();
  const [artistId, setArtistId] = useState("");
  const [consent, setConsent] = useState(false);
  const [model, setModel] = useState("ace-step-1.5-turbo");
  const [error, setError] = useState("");

  const artists = useQuery({
    queryKey: ["artist-profiles"],
    queryFn: () => api.get<ArtistRow[]>("/api/v1/artist-profiles"),
    retry: false,
  });
  const selected = artistId || artists.data?.[0]?.profile_id || "";
  const base = `/api/v1/artist-profiles/${selected}`;

  const status = useQuery({
    queryKey: ["voice-status", selected],
    queryFn: () => api.get<VoiceStatus>(`${base}/voice/status`),
    enabled: !!selected,
    refetchInterval: 10000,
  });
  const dataset = useQuery({
    queryKey: ["voice-dataset", selected],
    queryFn: async () => {
      try {
        return await api.get<DatasetResp>(`${base}/voice/dataset`);
      } catch (e) {
        if (e instanceof ApiError && e.status === 404) return null;
        throw e;
      }
    },
    enabled: !!selected,
  });
  const compat = useQuery({
    queryKey: ["voice-compat", selected],
    queryFn: () => api.get<{ models: CompatRow[] }>(`${base}/voice/compatibility`),
    enabled: !!selected,
  });
  const caps = useQuery({
    queryKey: ["voice-capabilities", selected],
    queryFn: () => api.get<Record<string, Capability>>(`${base}/voice/adapters/capabilities`),
    enabled: !!selected,
  });

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["voice-status", selected] });
    qc.invalidateQueries({ queryKey: ["voice-dataset", selected] });
    qc.invalidateQueries({ queryKey: ["voice-compat", selected] });
  };
  function run<T, V = void>(fn: (v: V) => Promise<T>) {
    return {
      mutationFn: fn,
      onSuccess: () => { setError(""); invalidate(); },
      onError: (e: Error) => setError(e.message),
    };
  }
  const createDataset = useMutation(run(() => api.post(`${base}/voice/dataset`)));
  const finalize = useMutation(run(() => api.post(`${base}/voice/dataset/finalize`)));
  const analyze = useMutation(run(() => api.post(`${base}/voice/analyze`)));
  const train = useMutation(run(() => api.post(`${base}/voice/train`, { model_selection: model })));
  const validate = useMutation(
    run((adapterId: string) => api.post(`${base}/voice/validate`, { adapter_id: adapterId })),
  );
  const remove = useMutation(
    run((recId: string) => api.delete(`${base}/voice/dataset/recordings/${recId}`)),
  );
  const upload = useMutation({
    mutationFn: async (file: File) => {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("consent", "artist consent confirmed in Voice Studio");
      const res = await fetch(`${base}/voice/dataset/recordings`, {
        method: "POST",
        body: fd,
        credentials: "include",
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(body?.error?.message || "Upload failed");
      return body as Recording;
    },
    onSuccess: () => { setError(""); invalidate(); },
    onError: (e: Error) => setError(e.message),
  });

  const trainable = useMemo(
    () => Object.values(caps.data || {}).filter((c) => c.training_recipe),
    [caps.data],
  );
  const busy = analyze.isPending || train.isPending || validate.isPending || upload.isPending;
  const recordings = dataset.data?.recordings || [];
  const frozen = (dataset.data?.latest_version_number || 0) > 0;
  const active = recordings.filter((r) => (r.qc?.verdict || "") !== "rejected");

  return (
    <main className="page">
      <div className="section-head" style={{ marginTop: 10 }}>
        <h2>Voice Studio</h2>
        <span className="sub">Artist voice datasets, adapters and compatibility</span>
      </div>
      <div className="card" style={{ maxWidth: 760 }}>
        <div className="field">
          <label>Artist</label>
          <select value={selected} onChange={(e) => setArtistId(e.target.value)}>
            {(artists.data || []).map((a) => (
              <option key={a.profile_id} value={a.profile_id}>{a.name}</option>
            ))}
          </select>
        </div>
        {error && <span className="pill err" style={{ marginBottom: 10 }}>{error}</span>}

        {!selected && <p className="sub">Create an artist profile first.</p>}

        {selected && !dataset.data && !dataset.isFetching && (
          <div style={{ marginTop: 10 }}>
            <p className="sub">This artist has no voice dataset yet.</p>
            <button className="btn btn-primary" disabled={createDataset.isPending} onClick={() => createDataset.mutate()}>
              {createDataset.isPending ? "Creating…" : "Create voice dataset"}
            </button>
          </div>
        )}

        {dataset.data && (
          <>
            <h3 style={{ marginTop: 18 }}>Recordings {frozen ? `· v${dataset.data.latest_version_number} frozen` : "· draft"}</h3>
            {recordings.map((r) => (
              <div key={r.recording_id} style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 13, marginBottom: 6 }}>
                <span style={{ minWidth: 200, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{r.filename}</span>
                <span className="sub">{r.duration_seconds != null ? `${Math.round(r.duration_seconds)}s` : ""}</span>
                <span className={`pill ${r.qc?.verdict === "rejected" ? "err" : r.qc?.verdict === "flagged" ? "warn" : "ok"}`}>
                  {r.qc?.verdict || "pending"}
                </span>
                <span className="spacer" style={{ flex: 1 }} />
                <button className="btn" disabled={remove.isPending || frozen} onClick={() => remove.mutate(r.recording_id)}>✕</button>
              </div>
            ))}
            <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", marginTop: 8 }}>
              <label className="btn" style={{ cursor: "pointer" }}>
                + Add recording
                <input type="file" accept=".wav,.flac,.mp3" hidden disabled={busy || frozen}
                  onChange={(e) => { const f = e.target.files?.[0]; if (f) upload.mutate(f); e.currentTarget.value = ""; }} />
              </label>
              <label style={{ fontSize: 12, display: "inline-flex", gap: 6, alignItems: "center" }}>
                <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
                consent on file
              </label>
              <span className="spacer" style={{ flex: 1 }} />
              <button className="btn" disabled={!active.length || busy} onClick={() => finalize.mutate()}>
                {finalize.isPending ? "Freezing…" : frozen ? "Freeze new version" : "Freeze version"}
              </button>
              <button className="btn" disabled={!frozen || busy} onClick={() => analyze.mutate()}>
                {analyze.isPending ? "Queued…" : "Analyze voice"}
              </button>
            </div>
            {dataset.data.latest_version?.report?.warnings?.map((w) => (
              <p key={w} className="sub" style={{ fontSize: 11 }}>⚠ {w}</p>
            ))}
          </>
        )}

        {frozen && (
          <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 14, flexWrap: "wrap" }}>
            <select value={model} onChange={(e) => setModel(e.target.value)}>
              {trainable.map((c) => (
                <option key={c.model_selection} value={c.model_selection}>
                  {c.model_selection}{c.adapter_load_verified ? "" : " (adapter load unverified)"}
                </option>
              ))}
            </select>
            <button className="btn btn-primary" disabled={busy} onClick={() => train.mutate()}>
              {train.isPending ? "Queued…" : "Train voice adapter"}
            </button>
            <span className="sub">50 credits · runs on a remote GPU worker</span>
          </div>
        )}

        {(status.data?.adapters || []).length > 0 && (
          <>
            <h3 style={{ marginTop: 18 }}>Adapters</h3>
            {status.data!.adapters.map((a) => (
              <div key={a.adapter_id} style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 13, marginBottom: 6 }}>
                <span style={{ minWidth: 170 }}>{a.model_selection}</span>
                <StatusPill status={a.state} label={STATE_LABEL_ADAPTER[a.state] || a.state} />
                <span className="sub">{a.state}{a.validation?.similarity != null ? ` · sim ${a.validation.similarity.toFixed(2)} vs ${a.validation.threshold}` : ""}</span>
                <span className="spacer" style={{ flex: 1 }} />
                {(a.state === "ready" || a.state === "stale") && (
                  <button className="btn" disabled={busy} onClick={() => validate.mutate(a.adapter_id)}>Validate</button>
                )}
              </div>
            ))}
          </>
        )}

        {(compat.data?.models || []).length > 0 && (
          <>
            <h3 style={{ marginTop: 18 }}>Model compatibility</h3>
            {compat.data!.models.map((m) => (
              <div key={m.model_selection} style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 13, marginBottom: 4 }}>
                <span style={{ minWidth: 170 }}>{m.model_selection}</span>
                <span className={`pill ${m.state === "NATIVE_ADAPTER_READY" ? "ok" : m.state === "FAILED" || m.state === "UNSUPPORTED" ? "err" : "warn"}`}>
                  {STATE_LABEL[m.state] || m.state}
                </span>
                {m.detail && <span className="sub" style={{ fontSize: 11 }}>{m.detail}</span>}
              </div>
            ))}
          </>
        )}

        {(status.data?.recent_jobs || []).length > 0 && (
          <>
            <h3 style={{ marginTop: 18 }}>Recent jobs</h3>
            {status.data!.recent_jobs.map((j) => (
              <div key={j.job_id} style={{ marginBottom: 10 }}>
                <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13 }}>
                  <strong>{j.operation}</strong>
                  <StatusPill status={j.status} />
                </div>
                <div className="sub" style={{ fontSize: 11 }}>
                  {j.stage ? `${j.stage}…` : j.status}
                  {j.progress != null ? ` · ${Math.round(j.progress * 100)}%` : ""}
                </div>
                <Progress value={j.progress ?? (j.status === "succeeded" ? 1 : 0)} />
              </div>
            ))}
          </>
        )}
      </div>
    </main>
  );
}
