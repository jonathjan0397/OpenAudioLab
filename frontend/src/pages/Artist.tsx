import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, AuthUser } from "../api";
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
  tracks: { asset_id: string; title: string | null; slug?: string | null; url: string }[];
}
interface Profile {
  profile_id: string;
  name: string;
  slug: string | null;
  bio?: string | null;
  avatar_key?: string | null;
  sharing_policy: string;
  etag: string;
  is_main: boolean;
  active_version_id: string | null;
}
interface ProfileSong {
  song_id: string;
  asset_id: string;
  title: string | null;
  position: number;
}
interface TrackRow {
  asset_id: string;
  title: string | null;
  slug?: string | null;
}

export default function ArtistPage() {
  const { slug } = useParams();
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const [bio, setBio] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const [assetToAdd, setAssetToAdd] = useState("");
  const [error, setError] = useState("");

  const me = useQuery({
    queryKey: ["me"],
    queryFn: () => api.get<{ user: AuthUser }>("/api/v1/auth/me"),
    retry: false,
  });
  const signedIn = !!me.data?.user;
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
  const profiles = useQuery({
    queryKey: ["artist-profiles"],
    queryFn: () => api.get<Profile[]>("/api/v1/artist-profiles"),
    enabled: signedIn && !slug,
  });
  const tracks = useQuery({
    queryKey: ["my-tracks"],
    queryFn: () => api.get<{ tracks: TrackRow[] }>("/api/v1/tracks?limit=50"),
    enabled: signedIn && !slug,
  });
  const songs = useQuery({
    queryKey: ["artist-songs", selected],
    queryFn: () => api.get<ProfileSong[]>(`/api/v1/artist-profiles/${selected}/songs`),
    enabled: !!selected,
  });
  const stats = useArtistStats(slug);

  const invalidateProfiles = () => {
    qc.invalidateQueries({ queryKey: ["artist-profiles"] });
    qc.invalidateQueries({ queryKey: ["public-artists"] });
  };
  const create = useMutation({
    mutationFn: () => api.post<Profile>("/api/v1/artist-profiles", { name, bio, style: {}, singer: {} }),
    onSuccess: (p) => {
      setName("");
      setBio("");
      setSelected(p.profile_id);
      setError("");
      invalidateProfiles();
    },
    onError: (e: Error) => setError(e.message),
  });
  const patch = useMutation({
    mutationFn: ({ id, etag, body }: { id: string; etag: string; body: Record<string, unknown> }) =>
      api.patch(`/api/v1/artist-profiles/${id}`, body, { "If-Match": etag }),
    onSuccess: invalidateProfiles,
    onError: (e: Error) => setError(e.message),
  });
  const setMain = useMutation({
    mutationFn: (id: string) => api.post<Profile>(`/api/v1/artist-profiles/${id}/set-main`, {}),
    onSuccess: invalidateProfiles,
    onError: (e: Error) => setError(e.message),
  });
  const addSong = useMutation({
    mutationFn: ({ profileId, assetId }: { profileId: string; assetId: string }) =>
      api.post(`/api/v1/artist-profiles/${profileId}/songs`, { asset_id: assetId }),
    onSuccess: () => {
      setAssetToAdd("");
      setError("");
      qc.invalidateQueries({ queryKey: ["artist-songs", selected] });
    },
    onError: (e: Error) => setError(e.message),
  });
  const removeSong = useMutation({
    mutationFn: ({ profileId, songId }: { profileId: string; songId: string }) =>
      api.delete(`/api/v1/artist-profiles/${profileId}/songs/${songId}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["artist-songs", selected] }),
    onError: (e: Error) => setError(e.message),
  });
  const uploadAvatar = useMutation({
    mutationFn: async ({ profileId, file }: { profileId: string; file: File }) => {
      const fd = new FormData();
      fd.append("file", file);
      const res = await fetch(`/api/v1/artist-profiles/${profileId}/avatar`, {
        method: "POST",
        body: fd,
        credentials: "include",
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(body?.error?.message || "Avatar upload failed");
      return body as { ok: boolean; avatar_key: string };
    },
    onSuccess: invalidateProfiles,
    onError: (e: Error) => setError(e.message),
  });

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
              <Link className="link" to={`/track/${t.slug || t.asset_id}`}>open →</Link>
              <audio controls src={t.url} style={{ width: "100%", marginTop: 8 }} />
            </div>
          ))}
        </div>
      </main>
    );
  }

  const selectedProfile = (profiles.data || []).find((p) => p.profile_id === selected);

  return (
    <main className="page">
      {signedIn && (
        <div className="card" style={{ marginBottom: 18 }}>
          <div className="card-header">
            <h2>My Artists</h2>
            <span className="spacer" />
            <span className="sub">Create a profile, upload an avatar, and curate songs.</span>
          </div>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 12 }}>
            <input style={{ width: 180 }} placeholder="artist name" value={name} onChange={(e) => setName(e.target.value)} />
            <input style={{ width: 260 }} placeholder="short bio" value={bio} onChange={(e) => setBio(e.target.value)} />
            <button className="btn btn-primary" disabled={!name.trim() || create.isPending} onClick={() => create.mutate()}>
              {create.isPending ? "Creating…" : "+ Create"}
            </button>
            {error && <span className="pill err">{error}</span>}
          </div>
          {[...(profiles.data || [])].sort((a, b) => (b.is_main ? 1 : 0) - (a.is_main ? 1 : 0)).map((p) => (
            <div key={p.profile_id} style={{ display: "flex", alignItems: "center", gap: 10, padding: "8px 0", borderBottom: "1px solid color-mix(in srgb, var(--border) 40%, transparent)" }}>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div className="title" style={{ fontSize: 14 }}>{p.is_main && <span title="Main profile" style={{ color: "var(--accent)" }}>★ </span>}{p.name}{p.is_main && <span className="sub" style={{ fontWeight: 400 }}> · Main</span>}{!p.is_main && <span className="sub" style={{ fontWeight: 400 }}> · sub-artist</span>}</div>
                <div className="sub" style={{ fontSize: 12 }}>/{p.slug} · {p.sharing_policy}{p.active_version_id ? "" : " · no trained version"}{p.bio ? ` · ${p.bio.slice(0, 48)}` : ""}</div>
              </div>
              <button className="btn" onClick={() => setSelected(selected === p.profile_id ? null : p.profile_id)}>
                {selected === p.profile_id ? "Hide songs" : "Songs"}
              </button>
              {!p.is_main && (
                <button className="btn btn-ghost" title="Make this the Main profile" disabled={setMain.isPending} onClick={() => setMain.mutate(p.profile_id)}>
                  Set main
                </button>
              )}
              <button className="btn" onClick={() => patch.mutate({ id: p.profile_id, etag: p.etag, body: { sharing: p.sharing_policy === "public" ? "private" : "public" } })}>
                {p.sharing_policy === "public" ? "Make private" : "Make public"}
              </button>
              <label className="btn" style={{ cursor: "pointer" }}>
                Avatar
                <input
                  type="file"
                  accept="image/*"
                  style={{ display: "none" }}
                  onChange={(e) => {
                    const file = e.target.files?.[0];
                    if (file) uploadAvatar.mutate({ profileId: p.profile_id, file });
                  }}
                />
              </label>
            </div>
          ))}
          {(profiles.data || []).length === 0 && <p style={{ color: "var(--muted)", fontSize: 13 }}>No artist profiles yet.</p>}
          {selectedProfile && (
            <div style={{ marginTop: 12 }}>
              <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 8, flexWrap: "wrap" }}>
                <strong>{selectedProfile.name} songs</strong>
                <select value={assetToAdd} onChange={(e) => setAssetToAdd(e.target.value)} style={{ minWidth: 220 }}>
                  <option value="">Choose a track…</option>
                  {(tracks.data?.tracks || []).map((t) => (
                    <option key={t.asset_id} value={t.asset_id}>{t.title || t.asset_id.slice(0, 8)}</option>
                  ))}
                </select>
                <button className="btn" disabled={!assetToAdd || addSong.isPending} onClick={() => addSong.mutate({ profileId: selectedProfile.profile_id, assetId: assetToAdd })}>
                  + Add
                </button>
              </div>
              {(songs.data || []).map((s) => (
                <div key={s.song_id} style={{ display: "flex", gap: 10, alignItems: "center", padding: "4px 0", fontSize: 13 }}>
                  <span style={{ flex: 1 }}>{s.title || s.asset_id.slice(0, 8)}</span>
                  <button className="btn btn-ghost" onClick={() => removeSong.mutate({ profileId: selectedProfile.profile_id, songId: s.song_id })}>✕</button>
                </div>
              ))}
              {(songs.data || []).length === 0 && <p style={{ color: "var(--muted)", fontSize: 13 }}>No curated songs yet.</p>}
            </div>
          )}
        </div>
      )}

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
