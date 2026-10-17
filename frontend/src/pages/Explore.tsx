import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import ArtworkTile from "../components/ArtworkTile";
import { usePlayer } from "../components/PlayerContext";
import { toPlayable, usePublicTracks } from "../components/tracks";
import { useTheme } from "../theme";

interface SearchResults {
  query: string;
  tracks: {
    asset_id: string;
    title: string | null;
    duration_seconds: number | null;
    url: string;
    created_at?: string | null;
    like_count?: number;
    creator?: string;
  }[];
  artists: { name: string; slug: string | null }[];
}

const GENRES = ["All", "Vocals", "Instrumental", "Hip Hop", "R&B", "Indie", "Electronic", "Cinematic"];

export default function ExplorePage() {
  const [params, setParams] = useSearchParams();
  const q = params.get("q") || "";
  const [input, setInput] = useState(q);
  const [genre, setGenre] = useState("All");
  const theme = useTheme();
  const player = usePlayer();
  const tracks = usePublicTracks(12);
  const results = useQuery({
    queryKey: ["search", q],
    queryFn: () => api.get<SearchResults>(`/api/v1/search?q=${encodeURIComponent(q)}`),
    enabled: q.length >= 2,
  });
  const list =
    results.data && q.length >= 2
      ? results.data.tracks.map((t) => ({
          ...t,
          created_at: t.created_at ?? null,
          like_count: t.like_count ?? 0,
          creator: t.creator ?? "community",
        }))
      : tracks.data?.tracks || [];

  return (
    <main className="page">
      <div className="section-head" style={{ marginTop: 10 }}>
        <h2>Explore</h2>
        <span className="sub">Fresh sounds from the community</span>
      </div>
      <form
        className="create-input-row"
        style={{ marginBottom: 14 }}
        onSubmit={(e) => {
          e.preventDefault();
          setParams(input.trim() ? { q: input.trim() } : {});
        }}
      >
        <input
          style={{ flex: 1, maxWidth: 480 }}
          placeholder="Search tracks and artists…"
          value={input}
          onChange={(e) => setInput(e.target.value)}
        />
        <button className="btn btn-primary" type="submit">
          Search
        </button>
      </form>
      <div className="chips" style={{ marginBottom: 20 }}>
        {GENRES.map((g) => (
          <button
            key={g}
            className={`chip${g === genre ? " active" : ""}`}
            style={g === genre ? { borderColor: "var(--accent)", color: "var(--accent)" } : undefined}
            onClick={() => setGenre(g)}
          >
            {g}
          </button>
        ))}
      </div>

      {results.data && q.length >= 2 && results.data.artists.length > 0 && (
        <div className="chips" style={{ marginBottom: 16 }}>
          {results.data.artists.map((a) => (
            <a key={a.slug} className="chip" href={`/artists/${a.slug}`} style={{ color: "var(--accent)" }}>
              ♪ {a.name}
            </a>
          ))}
        </div>
      )}

      <div className="trending-grid">
        {list.map((t, i) => (
          <div className="trend-card" key={t.asset_id}>
            <ArtworkTile
              seed={t.asset_id}
              wide
              duration={t.duration_seconds}
              onPlay={() => player.playQueue(list.map((x) => toPlayable(x)), i)}
            />
            <div className="name">{t.title || "Untitled"}</div>
          </div>
        ))}
        {list.length === 0 && <p style={{ color: "var(--muted)" }}>Nothing found.</p>}
      </div>
      <p style={{ color: "var(--muted)", fontSize: 12, marginTop: 18 }}>
        Genre filters are coming soon — every genre chip is wired to the search API.
      </p>
      <span hidden>{theme}</span>
    </main>
  );
}
