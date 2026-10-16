import CreateWidget from "../../components/CreateWidget";
import NowPlaying from "../../components/NowPlaying";
import ArtworkTile from "../../components/ArtworkTile";
import { usePlayer } from "../../components/PlayerContext";
import { usePublicTracks, toPlayable } from "../../components/tracks";
import { themeAvatar, useTheme } from "../../theme";

const FADERS = [
  ["Master", "0.0 dB", "var(--accent)"],
  ["Drums", "-1.2 dB", "var(--accent-2)"],
  ["Bass", "-0.8 dB", "var(--accent-2)"],
  ["Synths", "-2.4 dB", "var(--accent-2)"],
  ["Pads", "-1.6 dB", "var(--accent-3)"],
  ["Guitar", "-8.0 dB", "var(--accent)"],
  ["Vocals", "-3.1 dB", "var(--accent-3)"],
  ["FX", "-4.2 dB", "var(--accent)"],
] as const;

export default function SignalMain() {
  const theme = useTheme();
  const player = usePlayer();
  const tracks = usePublicTracks(5);
  const list = tracks.data?.tracks || [];

  return (
    <main className="sig-main">
      <section className="sig-hero">
        <div className="sig-hero-art" aria-hidden />
        <div className="sig-hero-copy">
          <div className="hero-kicker">Signal Lab</div>
          <h1 className="hero-title">
            Build your sound
            <br />
            from the <span className="lime">signal up.</span>
          </h1>
          <p className="hero-sub">
            Turn ideas into high-quality music with controllable generation, real artists profiles,
            and studio-grade tools.
          </p>
        </div>
        <div className="sig-rail">
          {["IDEA", "GENERATE", "REFINE", "EXPORT"].map((w) => (
            <span key={w}>{w}</span>
          ))}
        </div>
      </section>

      <div className="sig-grid">
        <div className="card sig-panel sig-create">
          <div className="panel-num">1</div>
          <div className="panel-title">Describe your track</div>
          <CreateWidget variant="panel" />
        </div>

        <div className="card sig-panel sig-profile">
          <div className="panel-head">
            <div className="panel-num">3</div>
            <div className="panel-title">Artist profile <span className="sub">(optional)</span></div>
            <span className="spacer" />
            <a className="link" href="/artists">View all →</a>
          </div>
          <div className="profile-tiles">
            <div className="ptile">
              <span className="ptile-none">⊘</span>
              <div className="pt-name">None</div>
              <div className="pt-sub">Neutral</div>
            </div>
            {["Nova", "Kael", "Lumi", "Riven"].map((n, i) => (
              <div className={`ptile${i === 0 ? " active" : ""}`} key={n}>
                <img src={themeAvatar(theme)} alt="" />
                <div className="pt-name">{n}</div>
                <div className="pt-sub">{["Electronic", "Alternative", "Pop", "Hip Hop"][i]}</div>
              </div>
            ))}
          </div>
        </div>

        <div className="card sig-panel sig-player">
          <NowPlaying tracks={list} big />
        </div>

        <div className="card sig-panel sig-variations">
          <div className="panel-head">
            <div className="panel-title">+ Variations</div>
            <span className="spacer" />
            <span className="link" style={{ color: "var(--accent-2)" }}>Regenerate all</span>
          </div>
          {list.slice(0, 4).map((t, i) => (
            <div className={`variation${i === 0 ? " active" : ""}`} key={t.asset_id}>
              <ArtworkTile seed={t.asset_id} size={40} onPlay={() => player.playQueue(list.map((x) => toPlayable(x)), i)} />
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontWeight: 600, fontSize: 13, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                  {t.title || "Untitled"}
                </div>
                <div style={{ fontSize: 11, color: "var(--muted)" }}>Electronic Pop · {Math.floor((t.duration_seconds || 0) / 60)}:{String(Math.round((t.duration_seconds || 0) % 60)).padStart(2, "0")}</div>
              </div>
              <span className="mono">⋮</span>
            </div>
          ))}
          {list.length === 0 && <p style={{ color: "var(--muted)", fontSize: 13 }}>Generate a track to see variations.</p>}
        </div>

        <div className="card sig-panel sig-mixer">
          <div className="panel-head">
            <div className="panel-title">⎈ Stem mixer</div>
            <span className="spacer" />
            <span className="pill muted" title="Stems coming soon">Studio Mix</span>
          </div>
          <div className="faders">
            {FADERS.map(([name, db, color]) => (
              <div className="fader" key={name} title="Stem separation coming soon">
                <span className="f-db">{db}</span>
                <span className="f-track">
                  <span className="f-knob" style={{ background: color, top: `${25 + (name === "Master" ? 0 : 15)}%` }} />
                </span>
                <span className="f-name" style={{ color }}>{name}</span>
              </div>
            ))}
          </div>
        </div>

        <div className="card sig-panel sig-export">
          <div className="panel-title">⇩ Export</div>
          <div className="export-cards">
            <button className="export-card active">
              <span className="ec-icon">⇊</span>
              <span><strong>WAV</strong><div className="ec-sub">High quality 44.1 kHz</div></span>
            </button>
            <button className="export-card" disabled title="Coming soon">
              <span className="ec-icon">♫</span>
              <span><strong>MP3</strong><div className="ec-sub">320 kbps</div></span>
            </button>
            <button className="export-card" disabled title="Coming soon">
              <span className="ec-icon">≋</span>
              <span><strong>WAV Stems</strong><div className="ec-sub">Individual tracks</div></span>
            </button>
          </div>
          <a className="btn btn-primary btn-lg" style={{ width: "100%", marginTop: 12 }} href={list[0]?.url || "#"} download>
            ⇩ Export Track
          </a>
        </div>
      </div>
    </main>
  );
}
