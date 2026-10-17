import CreateWidget from "../../components/CreateWidget";
import NowPlaying from "../../components/NowPlaying";
import ArtworkTile from "../../components/ArtworkTile";
import { usePlayer } from "../../components/PlayerContext";
import { usePublicTracks, toPlayable } from "../../components/tracks";
import { themeAvatar, themeArt, useTheme } from "../../theme";
import { FollowButton, usePublicArtists } from "../../components/social";
import { fmtCount, useSpotlight } from "../../components/tracks";

export default function OpenCanvasMain() {
  const theme = useTheme();
  const player = usePlayer();
  const tracks = usePublicTracks(5);
  const artists = usePublicArtists();
  const spot = useSpotlight();
  const list = tracks.data?.tracks || [];

  return (
    <main className="oc-main">
      <section className="oc-hero">
        <div className="oc-hero-art" aria-hidden />
        <div className="oc-hero-copy">
          <div className="hero-kicker">Open Canvas</div>
          <h1 className="hero-title">
            Make the music
            <br />
            in your head.
          </h1>
          <p className="hero-sub">
            Turn your ideas into original music with AI. Describe a vibe, choose your style, and
            create studio-quality tracks in seconds.
          </p>
        </div>
        <span className="hero-note oc-note-b">Ideas to music ↗</span>
      </section>

      <CreateWidget variant="wide" showStyle />
      <NowPlaying tracks={list} />

      <div className="oc-cols">
        <section>
          <div className="section-head">
            <h2>Trending Creations</h2>
            <span className="sub">Fresh tracks from the community</span>
            <span className="spacer" />
            <a className="link" href="/artists">View all →</a>
          </div>
          <div className="trending-grid oc-trending">
            {list.map((t, i) => (
              <div className="trend-card" key={t.asset_id}>
                <ArtworkTile
                  seed={t.asset_id}
                  wide
                  duration={t.duration_seconds}
                  onPlay={() => player.playQueue(list.map((x) => toPlayable(x)), i)}
                />
                <div className="name">{t.title || "Untitled"}</div>
                <div className="by">
                  <img className="avatar sm round" src={themeAvatar(theme)} alt="" />
                  {t.creator}
                  <span className="spacer" />
                  <span className="likes">♥ {t.like_count}</span>
                </div>
              </div>
            ))}
            {list.length === 0 && <p style={{ color: "var(--muted)" }}>Nothing shared yet.</p>}
          </div>
        </section>

        <aside className="card spotlight">
          <div className="card-header">
            <h3>Artist Spotlight</h3>
            <span className="spacer" />
            <a className="link" href="/artists">View all →</a>
          </div>
          <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
            <img className="avatar round" style={{ width: 52, height: 52 }} src={themeAvatar(theme)} alt="" />
            <div style={{ flex: 1 }}>
              <strong>{spot.data?.artist?.name || "Luna Waverly"}</strong>
              <div style={{ fontSize: 12, color: "var(--muted)" }}>Producer · Songwriter · Explorer</div>
            </div>
            <FollowButton slug={spot.data?.artist?.slug ?? artists.data?.artists?.[0]?.slug} />
          </div>
          <div className="spot-thumbs">
            {list.slice(0, 6).map((t) => (
              <img key={t.asset_id} src={themeArt(theme, t.asset_id)} alt="" />
            ))}
            {list.length === 0 && [0, 1, 2, 3, 4, 5].map((i) => <img key={i} src={themeArt(theme, `x${i}`)} alt="" />)}
          </div>
          <div style={{ display: "flex", gap: 18, marginTop: 12 }}>
            {[[fmtCount(spot.data?.artist?.tracks), "Tracks"], [fmtCount(spot.data?.artist?.followers), "Followers"], [fmtCount(spot.data?.artist?.plays), "Plays"]].map(([v, l]) => (
              <div key={l}>
                <div style={{ fontWeight: 800, fontSize: 17 }}>{v}</div>
                <div style={{ fontSize: 11, color: "var(--muted)" }}>{l}</div>
              </div>
            ))}
          </div>
          <p style={{ fontSize: 13, color: "var(--muted)", marginTop: 12 }}>
            Dreamy soundscapes, real emotions. Making music for a kinder, brighter world.
          </p>
        </aside>
      </div>
    </main>
  );
}
