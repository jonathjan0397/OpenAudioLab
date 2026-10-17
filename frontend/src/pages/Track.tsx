import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import ArtworkTile from "../components/ArtworkTile";
import { Playable, usePlayer } from "../components/PlayerContext";
import { toast } from "../components/Toast";
import Waveform from "../components/Waveform";
import { Avatar, fmtTime } from "../components/ui";

interface TrackInfo {
  asset_id: string;
  title: string;
  duration_seconds: number | null;
  created_at: string | null;
  like_count: number;
  creator: string;
  url: string;
}

async function copyLink(url: string) {
  try {
    await navigator.clipboard.writeText(url);
    toast("Link copied to clipboard");
  } catch {
    const el = document.createElement("textarea");
    el.value = url;
    document.body.appendChild(el);
    el.select();
    document.execCommand("copy");
    el.remove();
    toast("Link copied to clipboard");
  }
}

export default function TrackPage() {
  const { assetId } = useParams();
  const player = usePlayer();
  const track = useQuery({
    queryKey: ["public-track", assetId],
    queryFn: () => api.get<TrackInfo>(`/api/v1/public/tracks/${assetId}`),
    enabled: !!assetId,
    retry: false,
  });

  if (track.isLoading) {
    return (
      <main className="page">
        <h1>Track</h1>
        <p style={{ color: "var(--muted)" }}>Loading…</p>
      </main>
    );
  }
  if (!track.data) {
    return (
      <main className="page">
        <h1>Track not found</h1>
        <p style={{ color: "var(--muted)" }}>This track is private, expired, or no longer exists.</p>
        <Link className="btn btn-primary" to="/explore">Browse Explore →</Link>
      </main>
    );
  }

  const t = track.data;
  const playable: Playable = { asset_id: t.asset_id, title: t.title, url: t.url, duration: t.duration_seconds, subtitle: t.creator };
  const isLive = player.current?.asset_id === t.asset_id;
  const playing = isLive && player.playing;
  const position = isLive ? player.position : 0;
  const progress = isLive ? player.progress : 0;
  const duration = isLive ? player.duration : t.duration_seconds || 0;
  const token = t.url.split("token=")[1];

  return (
    <main className="page">
      <div className="hero-strip">
        <div>
          <h1>{t.title}</h1>
          <div className="sub">
            <Avatar name={t.creator} sm /> {t.creator} · ♥ {t.like_count}
            {t.created_at ? ` · ${t.created_at.slice(0, 10)}` : ""}
          </div>
        </div>
        <div className="strip-controls">
          <button className="btn" onClick={() => copyLink(`${window.location.origin}/track/${t.asset_id}`)}>Share</button>
          <a className="btn" href={t.url} download>⇊ WAV</a>
        </div>
      </div>
      <div className="card" style={{ marginTop: 20, display: "flex", gap: 20, alignItems: "center", flexWrap: "wrap" }}>
        <ArtworkTile seed={t.asset_id} size={180} onPlay={() => (isLive ? player.toggle() : player.play(playable))} />
        <div style={{ flex: 1, minWidth: 260 }}>
          <div style={{ display: "flex", gap: 12, alignItems: "center", marginBottom: 10 }}>
            <button className={`np-play${playing ? " on" : ""}`} onClick={() => (isLive ? player.toggle() : player.play(playable))} aria-label={playing ? "Pause" : "Play"}>
              {playing ? "❚❚" : "▶"}
            </button>
            <span className="mono" style={{ color: "var(--muted)", fontSize: 12 }}>
              {fmtTime(position)} / {fmtTime(duration)}
            </span>
          </div>
          <Waveform
            assetId={t.asset_id}
            token={token}
            progress={progress}
            onSeek={(r) => {
              if (!isLive) player.play(playable);
              setTimeout(() => player.seek(r), 60);
            }}
            height={56}
          />
        </div>
      </div>
      <p style={{ color: "var(--muted)", fontSize: 12, marginTop: 14 }}>
        <Link className="link" to="/explore">← Back to Explore</Link>
      </p>
    </main>
  );
}
