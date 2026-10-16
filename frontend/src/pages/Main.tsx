import CreateWidget from "../components/CreateWidget";
import Trending from "../components/Trending";

export default function MainPage() {
  return (
    <main className="page" style={{ display: "grid", gap: 32 }}>
      <section>
        <h1 style={{ fontSize: 44, marginBottom: 4 }}>Make the music in your head.</h1>
        <p style={{ color: "var(--muted)", maxWidth: 560 }}>
          Turn your ideas into original music with AI. Describe a vibe, choose your style, and
          create studio-quality tracks in seconds.
        </p>
      </section>
      <CreateWidget />
      <Trending />
    </main>
  );
}
