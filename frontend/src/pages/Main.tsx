import { ReactNode } from "react";
import CreateWidget from "../components/CreateWidget";
import Trending from "../components/Trending";

const HEROES: Record<string, { kicker: string; title: ReactNode; sub: string; note?: string }> = {
  "open-canvas": {
    kicker: "Open Canvas",
    title: <>Make the music in&nbsp;your head.</>,
    sub: "Turn your ideas into original music with AI. Describe a vibe, choose your style, and create studio-quality tracks in seconds.",
    note: "Describe any sound…",
  },
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
    note: "Real music. Real artists.",
  },
  "signal-lab": {
    kicker: "Signal Lab",
    title: (
      <>
        Build your sound
        <br />
        from the <span className="lime">signal up.</span>
      </>
    ),
    sub: "Turn ideas into high-quality music with controllable generation, real artist profiles, and studio-grade tools.",
  },
};

export default function MainPage() {
  const theme = document.documentElement.dataset.theme || "open-canvas";
  const hero = HEROES[theme] || HEROES["open-canvas"];
  return (
    <main className="page main-layout">
      <section className="main-hero">
        <div className="hero-copy">
          <div className="hero-kicker">{hero.kicker}</div>
          <h1 className="hero-title">{hero.title}</h1>
          <p className="hero-sub">{hero.sub}</p>
          {hero.note && <p className="hero-note">↖ {hero.note}</p>}
        </div>
        <div className="hero-art" aria-hidden="true" />
      </section>
      <div className="main-cols">
        <div style={{ display: "grid", gap: 8, minWidth: 0 }}>
          <CreateWidget />
          <Trending />
        </div>
        <aside className="card spotlight">
          <div className="card-header">
            <h3>Artist Spotlight</h3>
            <span className="spacer" />
            <a className="link" href="/artists">View all →</a>
          </div>
          <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
            <span className="avatar" style={{ width: 46, height: 46, fontSize: 16 }}>LW</span>
            <div>
              <strong>Luna Waverly</strong>
              <div style={{ fontSize: 12, color: "var(--muted)" }}>Producer · Songwriter · Explorer</div>
            </div>
          </div>
          <p style={{ fontSize: 13, color: "var(--muted)", marginTop: 12 }}>
            Dreamy soundscapes, real emotions. Making music for a kinder, brighter world.
          </p>
          <div style={{ display: "flex", gap: 18, marginTop: 12 }}>
            {[
              ["12", "Tracks"],
              ["8.4K", "Followers"],
              ["1.2M", "Plays"],
            ].map(([v, l]) => (
              <div key={l}>
                <div style={{ fontWeight: 800, fontSize: 17 }}>{v}</div>
                <div style={{ fontSize: 11, color: "var(--muted)" }}>{l}</div>
              </div>
            ))}
          </div>
        </aside>
      </div>
    </main>
  );
}
