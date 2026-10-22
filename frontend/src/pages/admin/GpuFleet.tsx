/* GPU Fleet console (GFAC): Smart Queue, swappiness settings, Top-10 Vast
   offers with manual deploy, deployments, instances, costs, events. */
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api";

const TABS = ["Overview", "Smart Queue", "Settings", "Offers", "Deployments", "Instances", "Costs", "Events"] as const;
type Tab = (typeof TABS)[number];

interface QueueView {
  models: { model_group: string; family: string; waiting: number; oldest_age_seconds: number }[];
  workers: { id: string; loaded_model: string | null; drain: boolean; quarantined: boolean; last_heartbeat: string | null }[];
  queue_depths: { main: number; burst: number } | null;
}
interface FleetSettings { settings: Record<string, unknown>; defaults: Record<string, unknown> }
interface Offer {
  rank?: number; offer_id: string; gpu: string | null; vram_gb: number | null; cuda: number | null;
  region: string | null; country: string | null; reliability: number | null; download_mbps: number | null;
  upload_mbps: number | null; disk_gb: number | null; dph: number | null; score?: number;
  est_ready_seconds: number | null;
}
interface OffersView { offers: Offer[]; eligible_count: number; excluded: Record<string, number>; refreshed_at?: string; cached: boolean }
interface Deployment {
  id: string; origin: string; purpose: string; state: string; state_reason: string | null;
  offer_id: string | null; contract: number | null; dph: number | null; automatic_shutdown: boolean;
  created_at: string | null;
}
const nr = (v: unknown, suffix = "") => (v === null || v === undefined || v === "" ? "Not reported" : `${v}${suffix}`);

interface OfferSearch { vram: number; dl: number; ul: number; limit: number }
const DEFAULT_SEARCH: OfferSearch = { vram: 24, dl: 1000, ul: 250, limit: 10 };
const offerPath = (s: OfferSearch, refresh = false) =>
  `/api/v1/admin/gpu-fleet/offers?min_vram=${s.vram}&min_download=${s.dl}&min_upload=${s.ul}&limit=${s.limit}${refresh ? "&refresh=true" : ""}`;

export default function GpuFleetPage() {
  const qc = useQueryClient();
  const [tab, setTab] = useState<Tab>("Overview");
  const [draft, setDraft] = useState<Record<string, unknown> | null>(null);
  const [deployOffer, setDeployOffer] = useState<Offer | null>(null);
  const [deployMsg, setDeployMsg] = useState("");
  const [search, setSearch] = useState<OfferSearch>(DEFAULT_SEARCH);
  const [osDraft, setOsDraft] = useState<OfferSearch>(DEFAULT_SEARCH);

  const overview = useQuery({ queryKey: ["fleet-overview"], queryFn: () => api.get<Record<string, number>>("/api/v1/admin/gpu-fleet"), enabled: tab === "Overview" });
  const queues = useQuery({ queryKey: ["fleet-queues"], queryFn: () => api.get<QueueView>("/api/v1/admin/gpu-fleet/queues"), enabled: tab === "Smart Queue", refetchInterval: tab === "Smart Queue" ? 5000 : false });
  const settings = useQuery({ queryKey: ["fleet-settings"], queryFn: () => api.get<FleetSettings>("/api/v1/admin/gpu-fleet/settings"), enabled: tab === "Settings" });
  const offers = useQuery({ queryKey: ["fleet-offers", search], queryFn: () => api.get<OffersView>(offerPath(search)), enabled: tab === "Offers", staleTime: 25000 });
  const deployments = useQuery({ queryKey: ["fleet-deployments"], queryFn: () => api.get<{ deployments: Deployment[] }>("/api/v1/admin/gpu-fleet/deployments"), enabled: tab === "Deployments" || tab === "Offers" });
  const costs = useQuery({ queryKey: ["fleet-costs"], queryFn: () => api.get<{ today_usd: number; combined_fleet_usd: number; categories_usd: Record<string, number>; running: { instance: string; hostname: string | null; dph: number; gpu: string | null }[] }>("/api/v1/admin/gpu-fleet/costs"), enabled: tab === "Costs" || tab === "Instances" || tab === "Overview" });
  const events = useQuery({ queryKey: ["fleet-events"], queryFn: () => api.get<{ events: { id: string; created_at: string | null; actor: string; action: string; subject: string | null }[]; decisions: Record<string, unknown>[] }>("/api/v1/admin/gpu-fleet/events"), enabled: tab === "Events" });

  const cur = { ...(settings.data?.settings || {}), ...(draft || {}) } as Record<string, any>;
  const dirty = draft !== null && JSON.stringify(draft) !== JSON.stringify(settings.data?.settings || {});

  const saveSettings = useMutation({
    mutationFn: () => api.patch<{ settings: Record<string, unknown> }>("/api/v1/admin/gpu-fleet/settings", draft || {}),
    onSuccess: () => { setDraft(null); qc.invalidateQueries({ queryKey: ["fleet-settings"] }); },
  });
  const deploy = useMutation({
    mutationFn: (offer: Offer) => api.post<{ deployment: Deployment; created: boolean }>("/api/v1/admin/gpu-fleet/deployments", {
      purpose: "auto", offer_id: offer.offer_id, idempotency_key: crypto.randomUUID?.() || String(Date.now()),
    }),
    onSuccess: (r) => { setDeployMsg(`Deployment ${r.deployment.id.slice(0, 8)} ${r.created ? "queued for provisioning" : "already requested"}.`); setDeployOffer(null); qc.invalidateQueries({ queryKey: ["fleet-deployments"] }); },
    onError: (e: Error) => setDeployMsg(`Deploy failed: ${e.message}`),
  });

  const num = (key: string, label: string, step = 1, min = 0, max = 100000) => (
    <label className="field" style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: 12 }}>
      {label}
      <input type="number" step={step} min={min} max={max} value={Number(cur[key] ?? 0)}
             onChange={(e) => setDraft({ ...(draft ?? settings.data?.settings ?? {}), [key]: Number(e.target.value) })} />
    </label>
  );

  return (
    <div className="card">
      <div className="card-header">
        <h2>GPU Fleet</h2>
        <span className="spacer" />
        <div className="segmented">
          {TABS.map((t) => (
            <button key={t} type="button" className={tab === t ? "active" : ""} onClick={() => setTab(t)}>{t}</button>
          ))}
        </div>
      </div>

      {tab === "Overview" && (
        <div className="stat-grid" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(160px, 1fr))" }}>
          {[
            ["Workers", overview.data?.workers ?? "—"],
            ["Ready", overview.data?.ready ?? "—"],
            ["Quarantined", overview.data?.quarantined ?? "—"],
            ["Local GPUs", overview.data?.local_gpus ?? "—"],
            ["Remote GPUs", overview.data?.remote_gpus ?? "—"],
            ["Active deployments", overview.data?.active_deployments ?? "—"],
            ["Spend today", `$${overview.data?.spend_today_usd ?? 0}`],
          ].map(([label, value]) => (
            <div key={String(label)} className="card stat-card">
              <div className="label">{label}</div>
              <div className="value">{value}</div>
            </div>
          ))}
        </div>
      )}

      {tab === "Smart Queue" && (
        <div style={{ overflowX: "auto" }}>
          <p className="sub" style={{ fontSize: 12 }}>
            Queue hints: main {queues.data?.queue_depths?.main ?? "?"} · burst {queues.data?.queue_depths?.burst ?? "?"}
            {" "}(PostgreSQL is authoritative; depths are delivery hints)
          </p>
          <table className="table">
            <thead><tr><th>Model group</th><th>Family</th><th>Waiting</th><th>Oldest wait</th></tr></thead>
            <tbody>
              {(queues.data?.models || []).map((m) => (
                <tr key={m.model_group}>
                  <td className="mono">{m.model_group}</td><td>{m.family}</td><td>{m.waiting}</td>
                  <td>{m.oldest_age_seconds > 0 ? `${Math.round(m.oldest_age_seconds)}s` : "—"}</td>
                </tr>
              ))}
              {(queues.data?.models || []).length === 0 && <tr><td colSpan={4} style={{ color: "var(--muted)" }}>No queued generation jobs.</td></tr>}
            </tbody>
          </table>
          <table className="table" style={{ marginTop: 12 }}>
            <thead><tr><th>Worker</th><th>Loaded checkpoint</th><th>State</th></tr></thead>
            <tbody>
              {(queues.data?.workers || []).map((w) => (
                <tr key={w.id}>
                  <td className="mono">{w.id}</td><td>{nr(w.loaded_model)}</td>
                  <td>{w.quarantined ? "quarantined" : w.drain ? "draining" : "online"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {tab === "Settings" && (
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          <label style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 13 }}>
            <input type="checkbox" checked={Boolean(cur.auto_burst_enabled)}
                   onChange={(e) => setDraft({ ...(draft ?? settings.data?.settings ?? {}), auto_burst_enabled: e.target.checked })} />
            Automatic burst scaling
          </label>
          <label style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: 12, maxWidth: 360 }}>
            Model swappiness: <strong>{Number(cur.swappiness ?? 50)} / 100</strong>
            <input type="range" min={0} max={100} step={25} value={Number(cur.swappiness ?? 50)}
                   onChange={(e) => setDraft({ ...(draft ?? settings.data?.settings ?? {}), swappiness: Number(e.target.value) })} />
            <span className="sub" style={{ fontSize: 11 }}>0 = depth-only · 25 conservative · 50 balanced · 75 aggressive · 100 maximum</span>
          </label>
          <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
            {num("max_auto_burst_workers", "Max auto workers", 1, 0, 3)}
            {num("max_dph", "Max $/hour", 0.05, 0.05, 1)}
            {num("min_vram_gb", "Min VRAM GB", 1, 8, 80)}
            {num("min_reliability", "Min reliability", 0.01, 0.5, 1)}
            {num("daily_burst_budget_usd", "Daily budget $", 0.5, 0, 1000)}
            {num("monthly_burst_budget_usd", "Monthly budget $", 5, 0, 1000)}
          </div>
          <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
            <button className="btn btn-primary" disabled={!dirty || saveSettings.isPending} onClick={() => saveSettings.mutate()}>
              {saveSettings.isPending ? "Saving…" : "Save Changes"}
            </button>
            {dirty && <span className="pill info">unsaved changes</span>}
            {saveSettings.isError && <span className="pill err">{(saveSettings.error as Error).message}</span>}
          </div>
        </div>
      )}

      {tab === "Offers" && (
        <div style={{ overflowX: "auto" }}>
          <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 8, flexWrap: "wrap" }}>
            <label style={{ fontSize: 12 }}>VRAM ≥
              <input type="number" min={24} max={80} value={osDraft.vram} style={{ width: 56, marginLeft: 4 }}
                onChange={(e) => setOsDraft({ ...osDraft, vram: Math.max(24, Number(e.target.value) || 24) })} /> GB
            </label>
            <label style={{ fontSize: 12 }}>Down ≥
              <input type="number" min={0} value={osDraft.dl} style={{ width: 64, marginLeft: 4 }}
                onChange={(e) => setOsDraft({ ...osDraft, dl: Math.max(0, Number(e.target.value) || 0) })} /> Mbps
            </label>
            <label style={{ fontSize: 12 }}>Up ≥
              <input type="number" min={0} value={osDraft.ul} style={{ width: 64, marginLeft: 4 }}
                onChange={(e) => setOsDraft({ ...osDraft, ul: Math.max(0, Number(e.target.value) || 0) })} /> Mbps
            </label>
            <label style={{ fontSize: 12 }}>Results
              <input type="number" min={1} max={50} value={osDraft.limit} style={{ width: 48, marginLeft: 4 }}
                onChange={(e) => setOsDraft({ ...osDraft, limit: Math.min(50, Math.max(1, Number(e.target.value) || 10)) })} />
            </label>
            <button className="btn" onClick={() => setSearch(osDraft)}>Search</button>
            <button className="btn btn-ghost" onClick={() => { setOsDraft(DEFAULT_SEARCH); setSearch(DEFAULT_SEARCH); }}>Reset</button>
            <button className="btn" onClick={() => {
              api.get<OffersView>(offerPath(search, true)).then((d) => {
                qc.setQueryData(["fleet-offers", search], d);
              });
            }}>Refresh</button>
            <span className="sub" style={{ fontSize: 12 }}>
              {offers.data?.refreshed_at ? `refreshed ${offers.data.refreshed_at.slice(11, 19)}Z${offers.data.cached ? " (cached)" : ""}` : "not yet fetched"}
              {offers.isFetching ? " · loading…" : ""}
            </span>
            {offers.isError && <span className="pill err">provider error — offers unavailable</span>}
            {offers.data && <span className="sub" style={{ fontSize: 12 }}>{offers.data.eligible_count} eligible</span>}
            {deployMsg && <span className="pill info">{deployMsg}</span>}
          </div>
          <table className="table">
            <thead>
              <tr><th>#</th><th>GPU</th><th>VRAM</th><th>CUDA</th><th>Region</th><th>Reliab.</th><th>Down</th><th>Up</th>
                  <th>Disk</th><th>$/hour</th><th>Est. ready</th><th>Score</th><th>Action</th></tr>
            </thead>
            <tbody>
              {(offers.data?.offers || []).map((o) => (
                <tr key={o.offer_id}>
                  <td>{o.rank}</td><td>{nr(o.gpu)}</td><td>{nr(o.vram_gb, " GB")}</td><td>{nr(o.cuda)}</td>
                  <td>{nr(o.region)}</td><td>{o.reliability != null ? `${Math.round(o.reliability * 100)}%` : "Not reported"}</td>
                  <td>{nr(o.download_mbps, " Mbps")}</td><td>{nr(o.upload_mbps, " Mbps")}</td>
                  <td>{nr(o.disk_gb, " GB")}</td><td>{o.dph != null ? `$${o.dph.toFixed(3)}` : "Not reported"}</td>
                  <td>{o.est_ready_seconds != null ? `${Math.round(o.est_ready_seconds / 60)} min` : "Not reported"}</td>
                  <td>{o.score?.toFixed(2)}</td>
                  <td><button className="btn" disabled={deploy.isPending} onClick={() => { setDeployOffer(o); setDeployMsg(""); }}>Deploy</button></td>
                </tr>
              ))}
              {(offers.data?.offers || []).length === 0 && !offers.isFetching && !offers.isError && (
                <tr><td colSpan={13} style={{ color: "var(--muted)" }}>
                  No Vast.ai instances currently meet the selected hardware, location, network and price requirements.
                </td></tr>
              )}
            </tbody>
          </table>
          {deployOffer && (
            <div className="card" style={{ marginTop: 10, padding: 12 }}>
              <strong>Deploy offer {deployOffer.offer_id}</strong>
              <div className="sub" style={{ fontSize: 12, margin: "6px 0" }}>
                {nr(deployOffer.gpu)} · {nr(deployOffer.vram_gb, " GB")} · {nr(deployOffer.region)} ·
                {deployOffer.dph != null ? ` $${deployOffer.dph.toFixed(3)}/hour` : " price not reported"} ·
                purpose: auto-compatible generation worker. Paid order; autoscaler provisions after confirmation.
              </div>
              <div style={{ display: "flex", gap: 8 }}>
                <button className="btn btn-primary" disabled={deploy.isPending} onClick={() => deploy.mutate(deployOffer)}>
                  {deploy.isPending ? "Requesting…" : "Confirm deploy"}
                </button>
                <button className="btn btn-ghost" onClick={() => setDeployOffer(null)}>Cancel</button>
              </div>
            </div>
          )}
        </div>
      )}

      {tab === "Deployments" && (
        <table className="table">
          <thead><tr><th>Created</th><th>Origin</th><th>Purpose</th><th>Offer</th><th>Contract</th><th>$/h</th><th>State</th><th>Reason</th></tr></thead>
          <tbody>
            {(deployments.data?.deployments || []).map((d) => (
              <tr key={d.id}>
                <td>{d.created_at?.slice(0, 16).replace("T", " ")}</td><td>{d.origin}</td><td>{d.purpose}</td>
                <td className="mono">{nr(d.offer_id)}</td><td>{nr(d.contract)}</td>
                <td>{d.dph != null ? `$${d.dph.toFixed(2)}` : "—"}</td>
                <td><span className={`pill ${d.state === "FAILED" ? "err" : d.state === "READY" ? "ok" : "info"}`}>{d.state}</span></td>
                <td>{nr(d.state_reason)}</td>
              </tr>
            ))}
            {(deployments.data?.deployments || []).length === 0 && <tr><td colSpan={8} style={{ color: "var(--muted)" }}>No deployments yet.</td></tr>}
          </tbody>
        </table>
      )}

      {tab === "Instances" && (
        <table className="table">
          <thead><tr><th>Instance</th><th>Hostname</th><th>GPU</th><th>$/hour</th></tr></thead>
          <tbody>
            {(costs.data?.running || []).map((v) => (
              <tr key={v.instance}><td className="mono">{v.instance}</td><td>{nr(v.hostname)}</td><td>{nr(v.gpu)}</td><td>${v.dph?.toFixed(3)}</td></tr>
            ))}
            {(costs.data?.running || []).length === 0 && <tr><td colSpan={4} style={{ color: "var(--muted)" }}>No paid instances running.</td></tr>}
          </tbody>
        </table>
      )}

      {tab === "Costs" && (
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          <div style={{ display: "flex", gap: 18, flexWrap: "wrap" }}>
            <div><div className="label">Today</div><div className="value">${costs.data?.today_usd ?? 0}</div></div>
            <div><div className="label">Combined fleet (recorded)</div><div className="value">${costs.data?.combined_fleet_usd ?? 0}</div></div>
          </div>
          <table className="table">
            <thead><tr><th>Category</th><th>USD</th></tr></thead>
            <tbody>
              {Object.entries(costs.data?.categories_usd || {}).map(([k, v]) => <tr key={k}><td>{k}</td><td>${v.toFixed(3)}</td></tr>)}
            </tbody>
          </table>
          <p className="sub" style={{ fontSize: 11 }}>Estimates from recorded dph × runtime; provider-reported accrued charges may differ.</p>
        </div>
      )}

      {tab === "Events" && (
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          <table className="table">
            <thead><tr><th>When</th><th>Swapp.</th><th>Queued</th><th>Local est</th><th>Remote est</th><th>Decision</th><th>Reason</th></tr></thead>
            <tbody>
              {(events.data?.decisions || []).slice(0, 20).map((d: any) => (
                <tr key={String(d.id)}>
                  <td>{String(d.created_at || "").slice(11, 19)}</td><td>{d.swappiness}</td><td>{d.queued_jobs}</td>
                  <td>{Math.round(d.est_local_wait_seconds)}s</td><td>{Math.round(d.est_remote_ready_seconds)}s</td>
                  <td>{d.decision}</td><td>{d.reason}</td>
                </tr>
              ))}
              {(events.data?.decisions || []).length === 0 && <tr><td colSpan={7} style={{ color: "var(--muted)" }}>No swappiness decisions recorded yet.</td></tr>}
            </tbody>
          </table>
          <table className="table">
            <thead><tr><th>When</th><th>Actor</th><th>Action</th><th>Subject</th></tr></thead>
            <tbody>
              {(events.data?.events || []).slice(0, 20).map((e) => (
                <tr key={e.id}><td>{e.created_at?.slice(11, 19)}</td><td>{e.actor}</td><td>{e.action}</td><td className="mono">{nr(e.subject)}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
