import { useEffect } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, AuthUser } from "../api";
import { toast } from "../components/Toast";

interface Plan {
  id: string;
  name: string;
  price_usd: number;
  monthly_credits: number;
}
interface Pack {
  id: string;
  name: string;
  price_usd: number;
  credits: number;
}
interface PlansResp {
  plans: Plan[];
  current: string;
  credits_balance: number;
  topup_credits: number;
}

const PERKS: Record<string, string[]> = {
  free: ["1,000 signup credits", "10 credits per generation", "WAV downloads", "Community sharing"],
  pro: ["2,500 credits / month", "MP3 + WAV exports", "Artist profiles", "Mood presets & LLM lyrics"],
  premier: ["10,000 credits / month", "6-stem separation", "Priority queue", "Custom artist training"],
};

export default function PricingPage() {
  const qc = useQueryClient();
  const plans = useQuery({ queryKey: ["billing-plans"], queryFn: () => api.get<PlansResp>("/api/v1/billing/plans") });
  const packs = useQuery({ queryKey: ["billing-packs"], queryFn: () => api.get<{ packs: Pack[] }>("/api/v1/billing/packs") });
  const me = useQuery({ queryKey: ["me"], queryFn: () => api.get<{ user: AuthUser }>("/api/v1/auth/me"), retry: false });

  useEffect(() => {
    const q = new URLSearchParams(window.location.search);
    if (q.get("checkout") === "success") {
      toast("Payment received — plan & credits updated");
      qc.invalidateQueries({ queryKey: ["billing-plans"] });
      qc.invalidateQueries({ queryKey: ["me"] });
      window.history.replaceState({}, "", "/pricing");
    } else if (q.get("checkout") === "cancel") {
      toast("Checkout cancelled");
      window.history.replaceState({}, "", "/pricing");
    }
  }, [qc]);

  const act = async (path: string, body?: unknown) => {
    const res = await fetch(`/api/v1/billing/${path}`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      credentials: "include",
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    if (res.status === 401) {
      toast("Sign in to manage your plan");
      return;
    }
    const data = await res.json();
    if (!res.ok) toast(data?.error?.message || "Something went wrong");
    else toast(path === "unsubscribe" ? "Back on the Free plan" : path === "topup" ? `+${data.added} credits added` : `${data.plan} plan active`);
    qc.invalidateQueries({ queryKey: ["billing-plans"] });
    qc.invalidateQueries({ queryKey: ["me"] });
  };

  const checkout = async (body: Record<string, unknown>, fallback: () => void) => {
    const res = await fetch("/api/v1/billing/checkout", {
      method: "POST",
      headers: { "content-type": "application/json" },
      credentials: "include",
      body: JSON.stringify(body),
    });
    if (res.status === 503) {
      fallback();
      return;
    }
    const data = await res.json();
    if (!res.ok) {
      toast(data?.error?.message || "Checkout failed");
      return;
    }
    window.location.href = data.url;
  };

  const signedIn = !!me.data?.user;
  const current = plans.data?.current || "free";

  return (
    <main className="page">
      <div className="section-head" style={{ marginTop: 10 }}>
        <h2>Pricing</h2>
        <span className="sub">
          Simple credits, no surprises{signedIn ? ` · balance ${plans.data?.credits_balance?.toLocaleString() ?? "…"}` : ""}
        </span>
      </div>
      <div className="stat-grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))" }}>
        {(plans.data?.plans || []).map((p) => {
          const isCurrent = p.id === current;
          return (
            <div key={p.id} className="card stat-card" style={p.id === "pro" ? { borderColor: "var(--accent)" } : undefined}>
              <div>
                <div className="label">{p.name}{p.id === "pro" ? " · most popular" : ""}</div>
                <div className="value" style={{ fontSize: 24 }}>{p.price_usd === 0 ? "Free" : `$${p.price_usd} / month`}</div>
                <ul style={{ margin: "10px 0 14px", paddingLeft: 18, fontSize: 13, color: "var(--muted)" }}>
                  {(PERKS[p.id] || []).map((perk) => (
                    <li key={perk}>{perk}</li>
                  ))}
                </ul>
                {signedIn &&
                  (isCurrent ? (
                    p.id === "free" ? (
                      <button className="btn" disabled>Current plan</button>
                    ) : (
                      <span style={{ display: "inline-flex", gap: 8 }}>
                        <button className="btn" disabled>Current plan</button>
                        <button className="btn btn-ghost" onClick={() => act("unsubscribe")}>Cancel</button>
                      </span>
                    )
                  ) : (
                    <button className="btn btn-primary" onClick={() => checkout({ kind: "plan", plan: p.id }, () => act("subscribe", { plan: p.id }))}>
                      Subscribe
                    </button>
                  ))}
              </div>
            </div>
          );
        })}
      </div>
      {signedIn && (
        <div className="card" style={{ marginTop: 20, padding: "16px 20px" }}>
          <div className="label" style={{ marginBottom: 10 }}>Credit packs (one-time)</div>
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
            {(packs.data?.packs || []).map((k) => (
              <button key={k.id} className="btn" onClick={() => checkout({ kind: "pack", pack: k.id }, () => act("topup"))}>
                {k.credits.toLocaleString()} credits — ${k.price_usd}
              </button>
            ))}
          </div>
        </div>
      )}
    </main>
  );
}
