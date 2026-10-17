import { useState } from "react";
import CreateWidget from "../../components/CreateWidget";
import ArtworkTile from "../../components/ArtworkTile";
import Waveform from "../../components/Waveform";
import { usePlayer } from "../../components/PlayerContext";
import { usePublicTracks, toPlayable } from "../../components/tracks";
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
              <button key={t} className={t === tab ? "active" : ""} disabled={t !== "Create"} onClick={() => setTab(t)}>
                {t}
              </button>
            ))}
          </div>
          <CreateWidget variant="panel" showStyle />
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
        </section>

        <aside className="card profile-card">
          <div className="pc-banner" style={{ backgroundImage: `url(${themeBanner(theme)})` }}>
            <div className="pc-banner-name">
              <img className="avatar round" style={{ width: 40, height: 40 }} src={themeAvatar(theme)} alt="" />
              <div>
                <strong>Luna Waverly</strong>
                <div style={{ fontSize: 11, color: "var(--muted)" }}>Electronic Producer</div>
              </div>
            </div>
          </div>
          <div className="pc-body">
            <p style={{ fontSize: 13, color: "var(--muted)" }}>
              Blending organic textures with electronic energy. Exploring a brighter future through sound.
            </p>
            <FollowButton slug={artists.data?.artists?.[0]?.slug} />
            <div style={{ display: "flex", gap: 18, marginTop: 14 }}>
              {[["24", "Tracks"], ["128K", "Followers"], ["4.2M", "Plays"]].map(([v, l]) => (
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
