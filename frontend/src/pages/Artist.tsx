import { useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api";

interface PublicArtist {
  profile_id: string;
  name: string;
  slug: string;
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

  if (slug) {
    if (artist.isLoading) return <main className="page"><p>Loading...</p></main>;
    if (artist.error || !artist.data)
      return <main className="page"><h1>Artist not found</h1></main>;
    return (
      <main className="page">
        <h1>{artist.data.name}</h1>
        {artist.data.tracks.length === 0 && <p style={{ color: "var(--muted)" }}>No shared tracks yet.</p>}
        {artist.data.tracks.map((t) => (
          <div className="card" key={t.asset_id} style={{ marginBottom: 10 }}>
            <strong>{t.title || "Untitled"}</strong>
            <audio controls src={t.url} style={{ width: "100%", marginTop: 8 }} />
          </div>
        ))}
      </main>
    );
  }
  return (
    <main className="page">
      <h1>Artists</h1>
      {(list.data || []).map((a) => (
        <div className="card" key={a.profile_id} style={{ marginBottom: 8 }}>
          <a href={`/artists/${a.slug}`}>{a.name}</a>
        </div>
      ))}
      {list.data?.length === 0 && <p style={{ color: "var(--muted)" }}>No public artists yet.</p>}
    </main>
  );
}
