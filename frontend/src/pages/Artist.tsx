import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { FollowButton } from "../components/social";
import { fmtCount, useArtistStats } from "../components/tracks";

interface PublicArtist {
  profile_id: string;
  name: string;
  slug: string;
  bio?: string | null;
  avatar_url?: string | null;
}
interface ArtistDetail extends PublicArtist {
  tracks: { asset_id: string; title: string | null; url: string }[];
}

export default function ArtistPage() {
  const { slug } = useParams();
  const list = useQuery({
    queryKey: ["public-artists"],
    queryFn: () => api.get<PublicArtist[]>("/api/v1/public/artists"),
    enabled: !slug,
  });
  const artist = useQuery({
    queryKey: ["public-artist", slug],
    queryFn: () => api.get<ArtistDetail>(`/api/v1/public/artists/${slug}`),
    enabled: !!slug,
  });
  const stats = useArtistStats(slug);

  if (slug) {
    if (artist.isLoading) return <main className="page"><p>Loading...</p></main>;
    if (artist.error || !artist.data)
      return <main className="page"><h1>Artist not found</h1></main>;
    return (
      <main className="page">
        <div className="hero-strip">
          <div style={{ display: "flex", gap: 14, alignItems: "center" }}>
            {artist.data.avatar_url && (
              <img src={artist.data.avatar_url} alt="" style={{ width: 72, height: 72, borderRadius: "50%", objectFit: "cover" }} />
            )}
            <div>
              <h1>{artist.data.name}</h1>
              <div className="sub">
                {fmtCount(stats.data?.tracks)} tracks · {fmtCount(stats.data?.followers)} followers · {fmtCount(stats.data?.plays)} plays
              </div>
              {artist.data.bio && <p style={{ marginTop: 6, maxWidth: 560 }}>{artist.data.bio}</p>}
            </div>
          </div>
          <div className="strip-controls">
            <FollowButton slug={artist.data.slug} />
          </div>
        </div>
        <div style={{ marginTop: 18 }}>
        {artist.data.tracks.length === 0 && <p style={{ color: "var(--muted)" }}>No shared tracks yet.</p>}
        {artist.data.tracks.map((t) => (
          <div className="card" key={t.asset_id} style={{ marginBottom: 10 }}>
            <strong>{t.title || "Untitled"}</strong>{" "}
            <Link className="link" to={`/track/${t.asset_id}`}>open →</Link>
            <audio controls src={t.url} style={{ width: "100%", marginTop: 8 }} />
          </div>
        ))}
        </div>
      </main>
    );
  }
  return (
    <main className="page">
      <h1>Artists</h1>
      {(list.data || []).map((a) => (
        <div className="card" key={a.profile_id} style={{ marginBottom: 8, display: "flex", alignItems: "center", gap: 12 }}>
          {a.avatar_url ? (
            <img src={a.avatar_url} alt="" style={{ width: 40, height: 40, borderRadius: "50%", objectFit: "cover" }} />
          ) : (
            <span style={{ width: 40, height: 40, borderRadius: "50%", background: "var(--surface-2, #333)", display: "inline-flex", alignItems: "center", justifyContent: "center" }}>☺</span>
          )}
          <div>
            <a href={`/artists/${a.slug}`}>{a.name}</a>
            {a.bio && <div className="sub" style={{ fontSize: 12 }}>{a.bio.slice(0, 80)}</div>}
          </div>
        </div>
      ))}
      {list.data?.length === 0 && <p style={{ color: "var(--muted)" }}>No public artists yet.</p>}
    </main>
  );
}
