import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../../api";
import CreateWidget from "../../components/CreateWidget";
import ArtworkTile from "../../components/ArtworkTile";
import Waveform from "../../components/Waveform";
import { usePlayer } from "../../components/PlayerContext";
import { fmtCount, usePublicTracks, useSpotlight, toPlayable } from "../../components/tracks";
import { themeAvatar, themeBanner, useTheme } from "../../theme";
import { FollowButton, usePublicArtists } from "../../components/social";
import { fmtTime } from "../../components/ui";

const HEROES: Record<string, { kicker: string; title: JSX.Element; sub: string; features?: [string, string, string][] }> = {
  "neon-studio": {
    kicker: "Neon Studio",
    title: (
      <>
        Your sound.
        <br />
        <span className="grad">Your rules.</span>
      </>
    ),
    sub: "Create, explore and share original music with next-generation AI. From ideas to full tracks, in your style.",
    features: [
      ["⚡", "Text to Music", "Turn ideas into tracks"],
      ["🎛", "Full Control", "Style, mood, structure"],
      ["👥", "A Global Community", "Artists, creators, explorers"],
    ],
  },
  "analog-soul": {
    kicker: "Analog Soul",
    title: (
      <>
        New technology.
        <br />
        Your signature sound.
      </>
    ),
    sub: "Train on your style. Create original music. Keep what makes you, you.",
    features: [
      ["⇍", "Your style learned", "not lost"],
      ["🎚", "Studio-quality", "generation"],
      ["☺", "Built for", "real artists"],
    ],
  },
};

export default function SplitMain() {
  const theme = useTheme();
  const player = usePlayer();
  const hero = HEROES[theme] || HEROES["neon-studio"];
  const tracks = usePublicTracks(4);
  const artists = usePublicArtists();
  const featuredArtists = useQuery({
    queryKey: ["featured-artists"],
    queryFn: () =>
      api.get<{ profile_id: string; name: string; slug: string; bio?: string | null; avatar_url?: string | null }[]>(
        "/api/v1/public/artists?limit=10"
      ),
    staleTime: 120000,
  });
  const spot = useSpotlight();
  const list = tracks.data?.tracks || [];
  const [tab, setTab] = useState("Create");

  return (
    <main className="split-main">
      <section className="split-hero">
        <div className="split-copy">
          <div className="hero-kicker">{hero.kicker} <span className="kicker-dash" /></div>
          <h1 className="hero-title">{hero.title}</h1>
          <p className="hero-sub">{hero.sub}</p>
          {hero.features && (
            <div className="split-features">
              {hero.features.map(([icon, t, s]) => (
                <div key={t} className="feat">
                  <span className="feat-icon" aria-hidden>{icon}</span>
                  <div>
                    <div style={{ fontWeight: 700, fontSize: 13 }}>{t}</div>
                    <div style={{ fontSize: 12, color: "var(--muted)" }}>{s}</div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
        <div className="split-art" aria-hidden />
        <aside className="split-panel">
          <div className="panel-tabs">
            {["Create", "Remix", "Extend", "Tools"].map((t) => (
              <button key={t} className={t === tab ? "active" : ""} onClick={() => setTab(t)}>
                {t}
              </button>
            ))}
          </div>
          {tab === "Tools" ? (
            <div className="card" style={{ padding: 16 }}>
              <p style={{ fontSize: 13, color: "var(--muted)", marginBottom: 12 }}>
                Studio tools for your library, jobs, and account.
              </p>
              <div style={{ display: "grid", gap: 8 }}>
                <a className="btn" href="/studio">♫ Studio — library & jobs →</a>
                <a className="btn" href="/lab">⚗ Lab — engine & LLM playground →</a>
                <a className="btn" href="/pricing">▥ Pricing & plans →</a>
              </div>
            </div>
          ) : (
            <CreateWidget variant="panel" showStyle mode={tab.toLowerCase() as "create" | "remix" | "extend"} />
          )}
        </aside>
      </section>

      <div className="split-cols">
        <section>
          <div className="section-head">
            <h2>{theme === "analog-soul" ? "Listening Gallery" : "Featured Tracks"}</h2>
            <span className="sub">Fresh sounds from our global community</span>
            <span className="spacer" />
            <a className="link" href="/artists">View All →</a>
          </div>
          <div className="featured-grid">
            {list.map((t, i) => (
              <div className="card featured-card" key={t.asset_id}>
                <div className="fc-top">
                  <ArtworkTile
                    seed={t.asset_id}
                    size={110}
                    onPlay={() => player.playQueue(list.map((x) => toPlayable(x)), i)}
                  />
                  <div className="fc-id">
                    <div className="fc-title">{t.title || "Untitled"}</div>
                    <div className="fc-by">
                      <img className="avatar sm round" src={themeAvatar(theme)} alt="" /> {t.creator}
                    </div>
                    <div className="chips">
                      <span className="chip">{fmtTime(t.duration_seconds)}</span>
                      <span className="chip">♥ {t.like_count}</span>
                    </div>
                  </div>
                </div>
                <div className="fc-wave">
                  <Waveform
                    assetId={t.asset_id}
                    token={t.url.split("token=")[1]}
                    progress={player.current?.asset_id === t.asset_id ? player.progress : 0}
                    onSeek={(r) => {
                      player.playQueue(list.map((x) => toPlayable(x)), i);
                      setTimeout(() => player.seek(r), 60);
                    }}
                    height={34}
                  />
                </div>
              </div>
            ))}
            {list.length === 0 && <p style={{ color: "var(--muted)" }}>Nothing shared yet.</p>}
          </div>

          <div className="section-head" style={{ marginTop: 26 }}>
            <h2>Featured Artists</h2>
            <span className="sub">Latest public profiles</span>
            <span className="spacer" />
            <a className="link" href="/artists">All artists →</a>
          </div>
          <div className="artist-strip">
            {(featuredArtists.data || []).slice(0, 10).map((a) => (
              <a className="artist-tile card" key={a.profile_id} href={`/artists/${a.slug}`}>
                {a.avatar_url ? (
                  <img src={a.avatar_url} alt="" className="avatar round" style={{ width: 44, height: 44 }} />
                ) : (
                  <span className="avatar round" style={{ width: 44, height: 44, background: "var(--surface-2, #333)", display: "inline-flex", alignItems: "center", justifyContent: "center" }}>☺</span>
                )}
                <span className="fc-title" style={{ fontSize: 13 }}>{a.name}</span>
              </a>
            ))}
            {(featuredArtists.data || []).length === 0 && <p style={{ color: "var(--muted)" }}>No public artists yet.</p>}
          </div>
        </section>

        <aside className="card profile-card">
          <div className="pc-banner" style={{ backgroundImage: `url(${themeBanner(theme)})` }}>
            <div className="pc-banner-name">
              <img className="avatar round" style={{ width: 40, height: 40 }} src={themeAvatar(theme)} alt="" />
              <div>
                <strong>{spot.data?.artist?.name || "Luna Waverly"}</strong>
                <div style={{ fontSize: 11, color: "var(--muted)" }}>Electronic Producer</div>
              </div>
            </div>
          </div>
          <div className="pc-body">
            <p style={{ fontSize: 13, color: "var(--muted)" }}>
              Blending organic textures with electronic energy. Exploring a brighter future through sound.
            </p>
            <FollowButton slug={spot.data?.artist?.slug ?? artists.data?.[0]?.slug} />
            <div style={{ display: "flex", gap: 18, marginTop: 14 }}>
              {[[fmtCount(spot.data?.artist?.tracks), "Tracks"], [fmtCount(spot.data?.artist?.followers), "Followers"], [fmtCount(spot.data?.artist?.plays), "Plays"]].map(([v, l]) => (
                <div key={l}>
                  <div style={{ fontWeight: 800 }}>{v}</div>
                  <div style={{ fontSize: 11, color: "var(--muted)" }}>{l}</div>
                </div>
              ))}
            </div>
          </div>
        </aside>
      </div>
    </main>
  );
}
