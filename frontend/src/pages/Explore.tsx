import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import ArtworkTile from "../components/ArtworkTile";
import { usePlayer } from "../components/PlayerContext";
import { toast } from "../components/Toast";
import { PublicTrack, fmtCount, toPlayable, usePublicTracks } from "../components/tracks";
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

const MOODS = ["All", "Hopeful", "Melancholic", "Energetic", "Calm", "Dreamy", "Dark"];

export default function ExplorePage() {
  const [params, setParams] = useSearchParams();
  const q = params.get("q") || "";
  const [input, setInput] = useState(q);
  const [mood, setMood] = useState("All");
  const theme = useTheme();
  const player = usePlayer();
  const qc = useQueryClient();
  const tracks = usePublicTracks(12, mood === "All" ? undefined : mood.toLowerCase());
  const results = useQuery({
    queryKey: ["search", q],
    queryFn: () => api.get<SearchResults>(`/api/v1/search?q=${encodeURIComponent(q)}`),
    enabled: q.length >= 2,
  });
  const searching = q.length >= 2 && !!results.data;
  const list: PublicTrack[] = searching
    ? (results.data?.tracks.map((t) => ({
        asset_id: t.asset_id,
        title: t.title,
        duration_seconds: t.duration_seconds,
        url: t.url,
        created_at: t.created_at ?? null,
        like_count: t.like_count ?? 0,
        creator: t.creator ?? "community",
      })) || [])
    : tracks.data?.tracks || [];

  const toggleFavorite = async (t: PublicTrack) => {
    const res = await fetch(`/api/v1/artifacts/${t.asset_id}/favorite`, { method: "POST", credentials: "include" });
    if (res.status === 401) toast("Sign in to favorite tracks");
    else if (!res.ok) toast("Could not favorite");
    qc.invalidateQueries({ queryKey: ["public-tracks"] });
  };

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
        {MOODS.map((g) => (
          <button
            key={g}
            className={`chip${g === mood ? " active" : ""}`}
            style={g === mood ? { borderColor: "var(--accent)", color: "var(--accent)" } : undefined}
            onClick={() => setMood(g)}
          >
            {g}
          </button>
        ))}
      </div>

      {searching && results.data!.artists.length > 0 && (
        <div className="chips" style={{ marginBottom: 16 }}>
          {results.data!.artists.map((a) => (
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
            <div style={{ display: "flex", gap: 10, alignItems: "center", fontSize: 12, color: "var(--muted)" }}>
              <button
                className="chip"
                style={{
                  padding: "2px 8px",
                  color: t.favorite ? "var(--accent)" : undefined,
                  borderColor: t.favorite ? "var(--accent)" : undefined,
                }}
                onClick={() => toggleFavorite(t)}
              >
                ♥ {fmtCount(t.like_count)}
              </button>
              {t.plays != null && <span className="mono">▶ {fmtCount(t.plays)}</span>}
              {t.tags && t.tags.length > 0 && <span>{t.tags[0]}</span>}
            </div>
          </div>
        ))}
        {list.length === 0 && <p style={{ color: "var(--muted)" }}>Nothing found.</p>}
      </div>
      <p style={{ color: "var(--muted)", fontSize: 12, marginTop: 18 }}>
        Mood chips filter the community feed by the mood chosen at creation time.
      </p>
      <span hidden>{theme}</span>
    </main>
  );
}
