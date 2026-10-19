import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import ArtworkTile from "./ArtworkTile";
import { usePlayer } from "./PlayerContext";

interface Track {
  asset_id: string;
  title: string | null;
  duration_seconds: number | null;
  url: string;
}

export default function Trending({ limit = 12 }: { limit?: number }) {
  const player = usePlayer();
  const tracks = useQuery({
    queryKey: ["public-tracks", limit],
    queryFn: () => api.get<{ tracks: Track[] }>(`/api/v1/public/tracks?limit=${limit}`),
  });
  return (
    <section>
      <div className="section-head">
        <h2>Trending Creations</h2>
        <span className="sub">Fresh tracks from the community</span>
        <span className="spacer" />
        <a className="link" href="/artists" style={{ fontSize: 13 }}>View all →</a>
      </div>
      {tracks.data?.tracks.length === 0 && (
        <p style={{ color: "var(--muted)" }}>Nothing shared yet — generate and share a track!</p>
      )}
      <div className="trending-grid">
        {tracks.data?.tracks.map((t) => (
          <div className="trend-card" key={t.asset_id}>
            <ArtworkTile
              seed={t.asset_id}
              wide
              duration={t.duration_seconds}
              onPlay={() =>
                player.play({
                  asset_id: t.asset_id,
                  title: t.title || "Untitled",
                  url: t.url,
                  duration: t.duration_seconds,
                  subtitle: "Community",
                })
              }
            />
            <div className="name">{t.title || "Untitled"}</div>
            <div className="by">
              <span className="avatar sm">OA</span> openaudiolab
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
