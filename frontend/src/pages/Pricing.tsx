import { useEffect } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, AuthUser } from "../api";
import { toast } from "../components/Toast";

interface Plan {
  id: string;
  name: string;
  price_usd: number;
  credits: number;
  monthly_credits?: number;
  visible?: boolean;
  popular?: boolean;
}
interface Pack {
  id: string;
  name: string;
  price_usd: number;
  credits: number;
  popular?: boolean;
}
interface PlansResp {
  plans: Plan[];
  current: string;
  credits_balance: number;
  subscription_status?: string | null;
  cancel_at_period_end?: boolean;
  current_period_end?: string | null;
  topup_credits: number;
}
interface PricingResp {
  plans: Plan[];
  packs: Pack[];
  guest: {
    daily_song_limit: number;
    max_duration_seconds: number;
    session_ttl_days: number;
  };
  policy_version: string;
}

const PERKS: Record<string, string[]> = {
  free: ["Turbo model access", "Premium SFT & XL models locked", "No monthly credits", "Top up any time with credit packs"],
  beginner: ["1,000 credits / month", "Guest allowance upgrade", "MP3 + WAV exports", "Private outputs"],
  pro: ["2,500 credits / month", "MP3 + WAV exports", "Artist profiles", "Mood presets & LLM lyrics"],
  premier: ["10,000 credits / month", "6-stem separation", "Priority queue", "Custom artist training"],
};

export default function PricingPage() {
  const qc = useQueryClient();
  const pricing = useQuery({ queryKey: ["billing-pricing"], queryFn: () => api.get<PricingResp>("/api/v1/billing/pricing") });
  const me = useQuery({ queryKey: ["me"], queryFn: () => api.get<{ user: AuthUser }>("/api/v1/auth/me"), retry: false });
  const signedIn = !!me.data?.user;
  const plans = useQuery({
    queryKey: ["billing-plans"],
    queryFn: () => api.get<PlansResp>("/api/v1/billing/plans"),
    enabled: signedIn,
  });
  const packs = useQuery({
    queryKey: ["billing-packs"],
    queryFn: () => api.get<{ packs: Pack[] }>("/api/v1/billing/packs"),
    enabled: signedIn,
  });

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
    else if (path === "unsubscribe") toast("Back on the Free plan");
    else if (path === "cancel") toast("Cancellation scheduled for period end");
    else if (path === "topup") toast(`+${data.added} credits added`);
    else toast(`${data.plan} plan active`);
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

  const current = plans.data?.current || me.data?.user?.plan || "free";

  return (
    <main className="page">
      <div className="section-head" style={{ marginTop: 10 }}>
        <h2>Pricing</h2>
        <span className="sub">
          Simple credits, no surprises{signedIn ? ` · balance ${plans.data?.credits_balance?.toLocaleString() ?? "…"}` : ""}
        </span>
      </div>
      {pricing.data && (
        <p className="sub" style={{ marginTop: -4 }}>
          Guests can create {pricing.data.guest.daily_song_limit} songs per UTC day up to{" "}
          {Math.round(pricing.data.guest.max_duration_seconds / 60)} minutes. Beginner is $5/month for 1,000 credits.
        </p>
      )}
      <div className="stat-grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))" }}>
        {(pricing.data?.plans || []).map((p) => {
          const isCurrent = p.id === current;
          return (
            <div key={p.id} className="card stat-card" style={p.popular ? { borderColor: "var(--accent)", position: "relative" } : undefined}>
              {p.popular && (
                <span className="pill info" style={{ position: "absolute", top: 10, right: 12, zIndex: 1 }}>Most Popular</span>
              )}
              <div>
                <div className="label">{p.name}</div>
                <div className="value" style={{ fontSize: 24 }}>{p.price_usd === 0 ? "Free" : `$${p.price_usd} / month`}</div>
                <ul style={{ margin: "10px 0 14px", paddingLeft: 18, fontSize: 13, color: "var(--muted)" }}>
                  {(PERKS[p.id] || []).map((perk) => (
                    <li key={perk}>{perk}</li>
                  ))}
                </ul>
                {signedIn ? (
                  isCurrent ? (
                    p.id === "free" ? (
                      <button className="btn" disabled>Current plan</button>
                    ) : (
                      <span style={{ display: "inline-flex", gap: 8 }}>
                        <button className="btn" disabled>Current plan</button>
                        <button
                          className="btn btn-ghost"
                          onClick={() => act(me.data?.user?.stripe_subscription_id ? "cancel" : "unsubscribe")}
                        >
                          {me.data?.user?.stripe_subscription_id ? "Cancel at period end" : "Cancel"}
                        </button>
                      </span>
                    )
                  ) : (
                    <button className="btn btn-primary" onClick={() => checkout({ kind: "plan", plan: p.id }, () => act("subscribe", { plan: p.id }))}>
                      Subscribe
                    </button>
                  )
                ) : (
                  <button className="btn" disabled>Sign in to subscribe</button>
                )}
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
              <button key={k.id} className="btn" style={k.popular ? { borderColor: "var(--accent)" } : undefined} onClick={() => checkout({ kind: "pack", pack: k.id }, () => act("topup"))}>
                {k.popular ? "★ " : ""}{k.credits.toLocaleString()} credits — ${k.price_usd}
              </button>
            ))}
          </div>
        </div>
      )}
    </main>
  );
}
