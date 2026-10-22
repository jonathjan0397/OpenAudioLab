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
}
interface VoiceGroup { id: string; name: string | null; embedding_model: string; member_count: number; confidence: number | null; state: string }
interface Dataset { id: string; name: string; recording_count: number; total_seconds: number; frozen_sha256: string }
interface Attempt { id: string; dataset_id: string; job_id: string | null; state: string; hours: number | null; spend_usd: number | null }
interface Recipe { id: string; name: string; base_model: string; method: string; adapter_ids: string[] }
interface Bundle { id: string; name: string; version: string; kind: string; base_model: string; state: string }
interface Channel { name: string; enabled: boolean; min_credits: number; bundle: { id: string; name: string; version: string; state: string } | null }
interface BrowseEntry { name: string; path: string; is_dir: boolean; bytes: number | null; mtime: string | null }
interface BrowseView { path: string; root: string; parent: string | null; entries: BrowseEntry[] }
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

  const browse = useQuery({
    queryKey: ["ml-browse", browsePath],
    queryFn: () => api.get<BrowseView>(`/api/v1/admin/model-lab/browse${browsePath ? `?path=${encodeURIComponent(browsePath)}` : ""}`),
    enabled: tab === "Catalog" && browseOpen,
  });
  const importSel = useMutation({
    mutationFn: () => api.post<{ source: { id: string; name: string }; counts: Record<string, number> }>(
      "/api/v1/admin/model-lab/import-selected",
      { source_name: srcName, paths: Object.keys(picked).filter((k) => picked[k]) }),
    onSuccess: (r) => {
      setPicked({});
      setMsg(`Imported ${srcName}: ${r.counts.new ?? 0} new, ${r.counts.duplicate ?? 0} duplicate, ${r.counts.excluded ?? 0} excluded.`);
      qc.invalidateQueries({ queryKey: ["ml-sources"] });
      qc.invalidateQueries({ queryKey: ["ml-recordings"] });
      qc.invalidateQueries({ queryKey: ["ml-overview"] });
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
      <div className="rounded border p-2">
        <button className={btn} onClick={() => setBrowseOpen(!browseOpen)}>
          {browseOpen ? "Hide TrueNAS import" : "Import from TrueNAS"}
        </button>
        {browseOpen && browse.data && (
          <div className="mt-2 space-y-1">
            <div className="flex items-center gap-2 text-xs">
              {browse.data.parent && <button className={btn} onClick={() => setBrowsePath(browse.data.parent)}>.. up</button>}
              <span className="font-mono">{browse.data.path}</span>
            </div>
            <div className="max-h-64 overflow-y-auto text-sm">
              {browse.data.entries.map((e) => e.is_dir ? (
                <div key={e.path} className="border-b py-0.5">
                  <button className="text-left" onClick={() => setBrowsePath(e.path)}>{e.name}/</button>
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
        <table className="w-full text-left text-sm">
          <thead><tr className="border-b"><th className="py-1">Title</th><th>Artist</th><th>Class</th><th>Identification</th><th>Review</th><th>Eligible</th><th /></tr></thead>
          <tbody>{(recordings.data?.recordings ?? []).map((r) => (
            <tr key={r.id} className="border-b">
              <td className="py-1">{nr(r.title)}</td><td>{nr(r.artist)}</td><td>{r.classification}</td>
              <td>{r.identify_status}</td><td>{r.review_status}</td><td>{r.dataset_eligible ? "yes" : "no"}</td>
              <td className="space-x-1 whitespace-nowrap">
                <button className={btn} onClick={() => act.mutate({ path: `/api/v1/admin/model-lab/recordings/${r.id}/identify`, method: "post" })}>Identify</button>
                <button className={btn} onClick={() => act.mutate({ path: `/api/v1/admin/model-lab/recordings/${r.id}/review`, method: "post", body: { decision: "approved" } })}>Approve</button>
                <button className={btn} onClick={() => act.mutate({ path: `/api/v1/admin/model-lab/recordings/${r.id}/voice-scan`, method: "post" })}>Voice scan</button>
              </td>
            </tr>
          ))}</tbody>
        </table>
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
          <table className="w-full text-left">
            <thead><tr className="border-b"><th className="py-1">Dataset</th><th>Recordings</th><th>Seconds</th><th>Frozen</th><th /></tr></thead>
            <tbody>{(datasets.data?.datasets ?? []).map((d) => (
              <tr key={d.id} className="border-b">
                <td className="py-1">{d.name}</td><td>{d.recording_count}</td><td>{d.total_seconds}</td>
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
