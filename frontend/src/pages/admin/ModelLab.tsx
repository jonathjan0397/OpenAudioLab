/* Model Lab console: catalog, identification, voice discovery, budgeted
   training, merges, bundles and release channels for the AI-engine catalog. */
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api";

const TABS = ["Overview", "Catalog", "Recordings", "Voice", "Training", "Merges", "Bundles", "Channels"] as const;
type Tab = (typeof TABS)[number];

interface Overview {
  sources: number; lanes: number;
  recordings_by_classification: Record<string, number>;
  recordings_by_identify_status: Record<string, number>;
  coverage: { recordings: number; total_seconds: number; distinct_performers: number; lanes: Record<string, { recordings: number; seconds: number }> };
  selection: Record<string, number>;
}
interface Source { id: string; name: string; path: string | null; status: string }
interface Recording {
  id: string; title: string | null; artist: string | null; duration_seconds: number | null;
  classification: string; identify_status: string; review_status: string; dataset_eligible: boolean;
  tags_state: string; lyrics_origin: string | null; lyrics_chars: number;
}
interface VoiceGroup { id: string; name: string | null; embedding_model: string; member_count: number; confidence: number | null; state: string }
interface Dataset { id: string; name: string; kind?: string; recording_count: number; total_seconds: number; frozen_sha256: string; report?: { splits?: Record<string, number> } }
interface Attempt { id: string; dataset_id: string; job_id: string | null; state: string; hours: number | null; spend_usd: number | null }
interface Recipe { id: string; name: string; base_model: string; method: string; adapter_ids: string[] }
interface Bundle { id: string; name: string; version: string; kind: string; base_model: string; state: string }
interface Channel { name: string; enabled: boolean; min_credits: number; bundle: { id: string; name: string; version: string; state: string } | null }
interface BrowseEntry { name: string; path: string; is_dir: boolean; bytes: number | null; mtime: string | null; n_audio?: number }
interface BrowseView { path: string; root: string; parent: string | null; entries: BrowseEntry[]; source?: string }
interface ImportBatch { id: string; source_id: string; state: string; scanned: number; counts: Record<string, number>; error: string | null }
interface Budget { name: string; max_hours: number; max_spend_usd: number; used_hours: number; spent_usd: number; state: string }

const nr = (v: unknown, suffix = "") => (v === null || v === undefined || v === "" ? "Not reported" : `${v}${suffix}`);
const btn = "rounded border px-2 py-0.5 text-xs";

export default function ModelLabPage() {
  const qc = useQueryClient();
  const [tab, setTab] = useState<Tab>("Overview");
  const [msg, setMsg] = useState("");
  const [browseOpen, setBrowseOpen] = useState(false);
  const [browsePath, setBrowsePath] = useState<string | null>(null);
  const [picked, setPicked] = useState<Record<string, boolean>>({});
  const [srcName, setSrcName] = useState("pilot-selection");
  const [recSel, setRecSel] = useState<Record<string, boolean>>({});
  const [tagsFilter, setTagsFilter] = useState("");
  const [lyricsEdit, setLyricsEdit] = useState<{ id: string; text: string } | null>(null);
  const [dsName, setDsName] = useState("voice-set-1");
  const [dsKind, setDsKind] = useState("style");
  const [dsAllowI, setDsAllowI] = useState(false);
  const [dsAllowS, setDsAllowS] = useState(false);

  const overview = useQuery({ queryKey: ["ml-overview"], queryFn: () => api.get<Overview>("/api/v1/admin/model-lab/overview"), enabled: tab === "Overview" });
  const sources = useQuery({ queryKey: ["ml-sources"], queryFn: () => api.get<{ sources: Source[] }>("/api/v1/admin/model-lab/sources"), enabled: tab === "Catalog" });
  const recordings = useQuery({ queryKey: ["ml-recordings"], queryFn: () => api.get<{ recordings: Recording[] }>("/api/v1/admin/model-lab/recordings?limit=100"), enabled: tab === "Recordings" });
  const groups = useQuery({ queryKey: ["ml-groups"], queryFn: () => api.get<{ groups: VoiceGroup[] }>("/api/v1/admin/model-lab/voice-groups"), enabled: tab === "Voice" });
  const datasets = useQuery({ queryKey: ["ml-datasets"], queryFn: () => api.get<{ datasets: Dataset[] }>("/api/v1/admin/model-lab/datasets"), enabled: tab === "Training" });
  const attempts = useQuery({ queryKey: ["ml-attempts"], queryFn: () => api.get<{ attempts: Attempt[] }>("/api/v1/admin/model-lab/attempts"), enabled: tab === "Training" });
  const budget = useQuery({ queryKey: ["ml-budget"], queryFn: () => api.get<Budget>("/api/v1/admin/model-lab/budget"), enabled: tab === "Training" });
  const recipes = useQuery({ queryKey: ["ml-recipes"], queryFn: () => api.get<{ recipes: Recipe[] }>("/api/v1/admin/model-lab/merge-recipes"), enabled: tab === "Merges" });
  const bundles = useQuery({ queryKey: ["ml-bundles"], queryFn: () => api.get<{ bundles: Bundle[] }>("/api/v1/admin/model-lab/bundles"), enabled: tab !== "Overview" && tab !== "Catalog" && tab !== "Recordings" && tab !== "Voice" && tab !== "Training" });
  const channels = useQuery({ queryKey: ["ml-channels"], queryFn: () => api.get<{ channels: Channel[] }>("/api/v1/admin/model-lab/release-channels"), enabled: tab === "Channels" });

  const batches = useQuery({
    queryKey: ["ml-batches"],
    queryFn: () => api.get<{ batches: ImportBatch[] }>("/api/v1/admin/model-lab/batches"),
    enabled: tab === "Catalog",
  });
  const browse = useQuery({
    queryKey: ["ml-browse", browsePath],
    queryFn: () => api.get<BrowseView>(`/api/v1/admin/model-lab/browse${browsePath ? `?path=${encodeURIComponent(browsePath)}` : ""}`),
    enabled: tab === "Catalog" && browseOpen,
  });
  const importSel = useMutation({
    mutationFn: () => api.post<{ sources: { id: string; name: string }[]; job_ids: string[] }>(
      "/api/v1/admin/model-lab/import-selected",
      { source_name: srcName, paths: Object.keys(picked).filter((k) => picked[k]) }),
    onSuccess: (r) => {
      setPicked({});
      setMsg(`Queued worker scan "${srcName}": ${r.job_ids.length} job(s) on the GPU box; `
        + "recordings appear as batches progress.");
      qc.invalidateQueries({ queryKey: ["ml-sources"] });
    },
    onError: (e: Error) => setMsg(`Import failed: ${e.message}`),
  });
  const act = useMutation({
    mutationFn: async ({ path, method, body }: { path: string; method: "post" | "put" | "patch"; body?: unknown }) => {
      try {
        return await (api[method] as (p: string, b?: unknown) => Promise<unknown>)(path, body);
      } catch (e) {
        throw new Error(e instanceof Error ? e.message : String(e));
      }
    },
    onSuccess: () => { qc.invalidateQueries(); setMsg(""); },
    onError: (e: Error) => setMsg(e.message),
  });

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-1">
        {TABS.map((t) => (
          <button key={t} className={`${btn} ${tab === t ? "bg-slate-700 text-white" : ""}`} onClick={() => setTab(t)}>{t}</button>
        ))}
      </div>
      {msg && <div className="rounded bg-amber-100 px-2 py-1 text-xs">{msg}</div>}
      {act.isError && <div className="rounded bg-red-100 px-2 py-1 text-xs">{(act.error as Error).message}</div>}

      {tab === "Overview" && overview.data && (
        <div className="grid grid-cols-2 gap-2 text-sm md:grid-cols-4">
          <Stat label="Sources" value={overview.data.sources} />
          <Stat label="Lanes" value={overview.data.lanes} />
          <Stat label="Recordings" value={overview.data.coverage.recordings} />
          <Stat label="Catalog hours" value={(overview.data.coverage.total_seconds / 3600).toFixed(1)} />
          <Stat label="Performers" value={overview.data.coverage.distinct_performers} />
          <Stat label="Selection replay %" value={overview.data.selection.replay_pct} />
          <Stat label="By review" value={Object.entries(overview.data.recordings_by_classification).map(([k, v]) => `${k}:${v}`).join(" ") || "—"} />
          <Stat label="By identification" value={Object.entries(overview.data.recordings_by_identify_status).map(([k, v]) => `${k}:${v}`).join(" ") || "—"} />
        </div>
      )}

      {tab === "Catalog" && (
        <div className="space-y-3">
      {(batches.data?.batches ?? []).length > 0 && (
        <div className="rounded border p-2 text-xs">
          <div className="mb-1 font-semibold">Worker scan batches</div>
          {batches.data!.batches.slice(0, 5).map((b) => (
            <div key={b.id} className="flex justify-between border-b py-0.5">
              <span className="font-mono">{b.source_id.slice(0, 8)}</span>
              <span>{b.state}</span>
              <span>{b.scanned} scanned</span>
              <span>{Object.entries(b.counts ?? {}).map(([k, v]) => `${k}:${v}`).join(" ")}</span>
              <span className="text-red-600">{b.error ?? ""}</span>
            </div>
          ))}
        </div>
      )}
      <div className="rounded border p-2">
        <button className={btn} onClick={() => setBrowseOpen(!browseOpen)}>
          {browseOpen ? "Hide TrueNAS browser" : "Browse TrueNAS (worker catalog)"}
        </button>
        <button className={btn} onClick={() => act.mutate({ path: "/api/v1/admin/model-lab/dirs/refresh", method: "post", body: {} })}>
          Refresh folder index
        </button>
        {browseOpen && browse.data && (
          <div className="mt-2 space-y-1">
            <div className="flex items-center gap-2 text-xs">
              {browse.data.parent && <button className={btn} onClick={() => setBrowsePath(browse.data.parent)}>.. up</button>}
              <span className="font-mono">{browse.data.path}</span>
              {browse.data.source === "dir_index" && <span className="rounded bg-slate-200 px-1">catalog</span>}
              <button className={btn} disabled={act.isPending}
                      onClick={() => act.mutate({
                        path: "/api/v1/admin/model-lab/scan-selected", method: "post",
                        body: { source_name: `scan-${browse.data.path.split("/").filter(Boolean).slice(-2).join("-").replace(/[^A-Za-z0-9-]/g, "").slice(0, 60)}-${Date.now().toString(36)}`,
                                roots: [browse.data.path] } })}>
                Scan this folder
              </button>
            </div>
            <div className="max-h-64 overflow-y-auto text-sm">
              {browse.data.entries.map((e) => e.is_dir ? (
                <div key={e.path} className="flex items-center justify-between border-b py-0.5">
                  <button className="text-left" onClick={() => setBrowsePath(e.path)}>{e.name}/</button>
                  {e.n_audio != null && e.n_audio > 0 && <span className="text-xs opacity-60">{e.n_audio} audio</span>}
                </div>
              ) : (
                <label key={e.path} className="flex items-center gap-2 border-b py-0.5">
                  <input type="checkbox" checked={!!picked[e.path]} onChange={() => setPicked({ ...picked, [e.path]: !picked[e.path] })} />
                  <span>{e.name}</span>
                  <span className="text-xs opacity-60">{e.bytes != null ? `${(e.bytes / 1048576).toFixed(1)} MB` : ""}</span>
                </label>
              ))}
              {browse.data.entries.length === 0 && <div className="text-xs opacity-60">No folders or audio files here.</div>}
            </div>
            <div className="flex items-center gap-2">
              <input className="rounded border px-2 py-1 text-xs" value={srcName} onChange={(ev) => setSrcName(ev.target.value)} placeholder="source name" />
              <button className={btn} disabled={Object.values(picked).filter(Boolean).length === 0 || importSel.isPending}
                      onClick={() => importSel.mutate()}>
                Import {Object.values(picked).filter(Boolean).length} selected
              </button>
            </div>
          </div>
        )}
        {browse.isError && <div className="mt-1 text-xs text-red-600">Browse unavailable: {(browse.error as Error).message}</div>}
      </div>
        <table className="w-full text-left text-sm">
          <thead><tr className="border-b"><th className="py-1">Source</th><th>Path</th><th>Status</th><th /></tr></thead>
          <tbody>{(sources.data?.sources ?? []).map((s) => (
            <tr key={s.id} className="border-b">
              <td className="py-1">{s.name}</td><td className="font-mono text-xs">{nr(s.path)}</td><td>{s.status}</td>
              <td><button className={btn} onClick={() => act.mutate({ path: `/api/v1/admin/model-lab/sources/${s.id}/import?preview=true`, method: "post" })}>Preview import</button></td>
            </tr>
          ))}</tbody>
        </table>
        </div>
      )}

      {tab === "Recordings" && (
        <div className="space-y-2">
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <label>tags_state
              <select className="ml-1 rounded border px-1" value={tagsFilter} onChange={(e) => setTagsFilter(e.target.value)}>
                <option value="">all</option><option>suspect</option><option>invalid</option>
                <option>parsed</option><option>unparsed</option>
              </select>
            </label>
            <span className="opacity-60">lyrics shown per row (never bulk text)</span>
            <button className={btn} disabled={!Object.values(recSel).some(Boolean) || act.isPending}
                    onClick={() => act.mutate({ path: "/api/v1/admin/model-lab/verify-selected", method: "post",
                                                 body: { recording_ids: Object.keys(recSel).filter((k) => recSel[k]) } })}>
              Verify selected (MusicBrainz)
            </button>
            <button className={btn} disabled={!Object.values(recSel).some(Boolean) || act.isPending}
                    onClick={() => act.mutate({ path: "/api/v1/admin/model-lab/lyrics-fetch-selected", method: "post",
                                                body: { recording_ids: Object.keys(recSel).filter((k) => recSel[k]) } })}>
              Fetch lyrics (lrclib)
            </button>
            <button className={btn} disabled={!Object.values(recSel).some(Boolean) || act.isPending}
                    onClick={() => act.mutate({ path: "/api/v1/admin/model-lab/rights/declare-selected", method: "post",
                                                body: { recording_ids: Object.keys(recSel).filter((k) => recSel[k]),
                                                        holder: "Owner (house library)", scope: "recording",
                                                        scopes: ["recording", "composition"],
                                                        evidence: "owned library, private training only" } })}>
              Declare rights (selected)
            </button>
            <button className={btn} disabled={!Object.values(recSel).some(Boolean) || act.isPending}
                    onClick={() => act.mutate({ path: "/api/v1/admin/model-lab/enrich-selected", method: "post",
                                                 body: { recording_ids: Object.keys(recSel).filter((k) => recSel[k]) } })}>
              Enrich with local LM (prep)
            </button>
          </div>
          <table className="w-full text-left text-sm">
            <thead><tr className="border-b"><th /><th className="py-1">Title</th><th>Artist</th><th>Tags</th><th>Lyrics</th><th>Identification</th><th>Review</th><th /></tr></thead>
            <tbody>{(recordings.data?.recordings ?? [])
              .filter((r) => !tagsFilter || r.tags_state === tagsFilter).map((r) => (
              <tr key={r.id} className="border-b align-top">
                <td className="py-1"><input type="checkbox" checked={!!recSel[r.id]}
                      onChange={() => setRecSel({ ...recSel, [r.id]: !recSel[r.id] })} /></td>
                <td>{nr(r.title)}</td><td>{nr(r.artist)}</td>
                <td className="text-xs">{r.tags_state}</td>
                <td className="text-xs">{r.lyrics_origin ?? "none"}{r.lyrics_chars ? ` (${r.lyrics_chars})` : ""}</td>
                <td className="text-xs">{r.identify_status}</td><td>{r.review_status}</td>
                <td className="space-x-1 whitespace-nowrap">
                  <button className={btn} onClick={() => act.mutate({ path: `/api/v1/admin/model-lab/recordings/${r.id}/identify`, method: "post" })}>Identify</button>
                  <button className={btn} onClick={() => act.mutate({ path: `/api/v1/admin/model-lab/recordings/${r.id}/verify`, method: "post" })}>Verify</button>
                  <button className={btn} onClick={() => act.mutate({ path: `/api/v1/admin/model-lab/recordings/${r.id}/lyrics-fetch`, method: "post" })}>Lyrics</button>
                  <button className={btn} onClick={() => act.mutate({ path: `/api/v1/admin/model-lab/recordings/${r.id}/review`, method: "post", body: { decision: "approved" } })}>Approve</button>
                  <button className={btn} onClick={() => act.mutate({ path: `/api/v1/admin/model-lab/recordings/${r.id}/voice-scan`, method: "post" })}>Voice scan</button>
                  <button className={btn} onClick={() => api.get<{ lyrics_text: string | null }>(
                              `/api/v1/admin/model-lab/recordings/${r.id}`)
                              .then((d) => setLyricsEdit({ id: r.id, text: d.lyrics_text ?? "" }))}>View lyrics</button>
                </td>
              </tr>
            ))}</tbody>
          </table>
          {lyricsEdit && (
            <div className="rounded border p-2 text-sm">
              <div className="mb-1 text-xs">Submitted lyrics are stored exactly as sent (SHA-256 recorded).</div>
              <textarea className="h-32 w-full rounded border p-2 font-mono text-xs"
                        value={lyricsEdit.text}
                        onChange={(e) => setLyricsEdit({ ...lyricsEdit, text: e.target.value })} />
              <div className="mt-1 flex gap-2">
                <button className={btn} onClick={() => act.mutate({
                    path: `/api/v1/admin/model-lab/recordings/${lyricsEdit.id}/lyrics`, method: "post",
                    body: { lyrics: lyricsEdit.text } })}>Save as submitted</button>
                <button className={btn} onClick={() => setLyricsEdit(null)}>Close</button>
              </div>
            </div>
          )}
        </div>
      )}

      {tab === "Voice" && (
        <div className="space-y-2">
          <button className={btn} onClick={() => act.mutate({ path: "/api/v1/admin/model-lab/voice-cluster", method: "post" })}>Recluster singers</button>
          <table className="w-full text-left text-sm">
            <thead><tr className="border-b"><th className="py-1">Group</th><th>Model</th><th>Members</th><th>Confidence</th><th>State</th><th /></tr></thead>
            <tbody>{(groups.data?.groups ?? []).map((g) => (
              <tr key={g.id} className="border-b">
                <td className="py-1">{nr(g.name, "")}{g.name === null && <span className="font-mono text-xs">{g.id.slice(0, 8)}</span>}</td>
                <td>{g.embedding_model}</td><td>{g.member_count}</td><td>{nr(g.confidence)}</td><td>{g.state}</td>
                <td className="space-x-1 whitespace-nowrap">
                  <button className={btn} onClick={() => act.mutate({ path: `/api/v1/admin/model-lab/voice-groups/${g.id}/review`, method: "post", body: { decision: "approve" } })}>Approve</button>
                  <button className={btn} onClick={() => act.mutate({ path: `/api/v1/admin/model-lab/voice-groups/${g.id}/review`, method: "post", body: { decision: "reject" } })}>Reject</button>
                </td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      )}

      {tab === "Training" && (
        <div className="space-y-3 text-sm">
          {budget.data && (
            <div className="flex items-center gap-3 rounded border p-2">
              <span>Budget <b>{budget.data.name}</b>: {budget.data.used_hours}/{budget.data.max_hours} h · ${budget.data.spent_usd}/{budget.data.max_spend_usd} · <b>{budget.data.state}</b></span>
              <button className={btn} onClick={() => act.mutate({ path: "/api/v1/admin/model-lab/budget", method: "put", body: { max_hours: 6, max_spend_usd: 3 } })}>Reset caps 6h/$3</button>
            </div>
          )}
          <div className="rounded border p-2 space-y-1">
            <div className="text-xs font-semibold">Freeze dataset (from Recordings-tab selection:
              {Object.values(recSel).filter(Boolean).length} picked)</div>
            <div className="flex flex-wrap items-center gap-2">
              <input className="rounded border px-2 py-1 text-xs" value={dsName} onChange={(e) => setDsName(e.target.value)} />
              <select className="rounded border px-1 text-xs" value={dsKind} onChange={(e) => setDsKind(e.target.value)}>
                <option value="style">style</option><option value="voice">voice</option>
              </select>
              <label className="text-xs"><input type="checkbox" checked={dsAllowI} onChange={() => setDsAllowI(!dsAllowI)} /> allow instrumental</label>
              <label className="text-xs"><input type="checkbox" checked={dsAllowS} onChange={() => setDsAllowS(!dsAllowS)} /> allow suspect tags</label>
              <button className={btn} disabled={!Object.values(recSel).some(Boolean) || act.isPending}
                      onClick={() => act.mutate({ path: "/api/v1/admin/model-lab/datasets", method: "post",
                          body: { name: dsName, kind: dsKind, recording_ids: Object.keys(recSel).filter((k) => recSel[k]),
                                  allow_instrumental: dsAllowI, allow_suspect: dsAllowS } })}>
                Freeze
              </button>
            </div>
          </div>
          <table className="w-full text-left">
            <thead><tr className="border-b"><th className="py-1">Dataset</th><th>Kind</th><th>Recordings</th><th>Seconds</th><th>Frozen</th><th /></tr></thead>
            <tbody>{(datasets.data?.datasets ?? []).map((d) => (
              <tr key={d.id} className="border-b">
                <td className="py-1">{d.name}</td><td>{d.kind ?? "style"}</td>
                <td>{d.recording_count}</td><td>{d.total_seconds}</td>
                <td className="font-mono text-xs">{d.frozen_sha256.slice(0, 12)}</td>
                <td><button className={btn} onClick={() => act.mutate({ path: `/api/v1/admin/model-lab/datasets/${d.id}/train`, method: "post" })}>Train</button></td>
              </tr>
            ))}</tbody>
          </table>
          <table className="w-full text-left">
            <thead><tr className="border-b"><th className="py-1">Attempt</th><th>State</th><th>Hours</th><th>Spend</th></tr></thead>
            <tbody>{(attempts.data?.attempts ?? []).map((a) => (
              <tr key={a.id} className="border-b"><td className="py-1 font-mono text-xs">{a.id.slice(0, 8)}</td><td>{a.state}</td><td>{nr(a.hours)}</td><td>{nr(a.spend_usd)}</td></tr>
            ))}</tbody>
          </table>
        </div>
      )}

      {tab === "Merges" && (
        <table className="w-full text-left text-sm">
          <thead><tr className="border-b"><th className="py-1">Recipe</th><th>Base</th><th>Method</th><th>Adapters</th><th /></tr></thead>
          <tbody>{(recipes.data?.recipes ?? []).map((r) => (
            <tr key={r.id} className="border-b">
              <td className="py-1">{r.name}</td><td>{r.base_model}</td><td>{r.method}</td><td>{r.adapter_ids.length}</td>
              <td><button className={btn} onClick={() => act.mutate({ path: `/api/v1/admin/model-lab/merge-recipes/${r.id}/run`, method: "post" })}>Run merge</button></td>
            </tr>
          ))}</tbody>
        </table>
      )}

      {tab === "Bundles" && (
        <table className="w-full text-left text-sm">
          <thead><tr className="border-b"><th className="py-1">Bundle</th><th>Version</th><th>Kind</th><th>State</th><th /></tr></thead>
          <tbody>{(bundles.data?.bundles ?? []).map((b) => (
            <tr key={b.id} className="border-b">
              <td className="py-1">{b.name}</td><td>{b.version}</td><td>{b.kind}</td><td>{b.state}</td>
              <td className="space-x-1 whitespace-nowrap">
                <button className={btn} onClick={() => act.mutate({ path: `/api/v1/admin/model-lab/bundles/${b.id}/eval-samples`, method: "post", body: {} })}>Eval A/B</button>
                <button className={btn} onClick={() => act.mutate({ path: `/api/v1/admin/model-lab/bundles/${b.id}/release`, method: "post" })}>Release</button>
                <button className={btn} onClick={() => act.mutate({ path: `/api/v1/admin/model-lab/bundles/${b.id}/retire`, method: "post" })}>Retire</button>
              </td>
            </tr>
          ))}</tbody>
        </table>
      )}

      {tab === "Channels" && (
        <table className="w-full text-left text-sm">
          <thead><tr className="border-b"><th className="py-1">Channel</th><th>Bundle</th><th>Min credits</th><th>Enabled</th><th /></tr></thead>
          <tbody>{(channels.data?.channels ?? []).map((c) => (
            <tr key={c.name} className="border-b">
              <td className="py-1">{c.name}</td>
              <td>{c.bundle ? `${c.bundle.name} ${c.bundle.version} (${c.bundle.state})` : "—"}</td>
              <td>{c.min_credits}</td><td>{c.enabled ? "yes" : "no"}</td>
              <td><button className={btn} onClick={() => act.mutate({ path: `/api/v1/admin/model-lab/release-channels/${c.name}`, method: "patch", body: { enabled: !c.enabled } })}>Toggle</button></td>
            </tr>
          ))}</tbody>
        </table>
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded border p-2">
      <div className="text-xs text-slate-500">{label}</div>
      <div className="font-semibold">{value}</div>
    </div>
  );
}
