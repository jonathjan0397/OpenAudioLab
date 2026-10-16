import { useQuery } from "@tanstack/react-query";
import { api } from "../api";

interface Track {
  asset_id: string;
  title: string | null;
  duration_seconds: number | null;
  url: string;
}

export default function Trending() {
  const tracks = useQuery({
    queryKey: ["public-tracks"],
    queryFn: () => api.get<{ tracks: Track[] }>("/api/v1/public/tracks?limit=12"),
  });
  return (
    <section>
      <h2>Trending Creations</h2>
      <p style={{ color: "var(--muted)" }}>Fresh tracks from the community</p>
      {tracks.data?.tracks.length === 0 && (
        <p style={{ color: "var(--muted)" }}>Nothing shared yet — generate and share a track!</p>
      )}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))", gap: 16 }}>
        {tracks.data?.tracks.map((t) => (
          <div className="card" key={t.asset_id}>
            <strong>{t.title || "Untitled"}</strong>
            <audio controls src={t.url} style={{ width: "100%", marginTop: 8 }} />
          </div>
        ))}
      </div>
    </section>
  );
}
