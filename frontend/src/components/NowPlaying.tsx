import ArtworkTile from "./ArtworkTile";
import Waveform from "./Waveform";
import { usePlayer } from "./PlayerContext";
import { exportArtifact } from "./social";
import { toast } from "./Toast";
import { PublicTrack, toPlayable } from "./tracks";
import { fmtTime } from "./ui";

/**
 * The reference "now playing" bar: artwork, identity, waveform transport,
 * volume and export cards. Falls back to the first trending track when
 * nothing is playing yet.
 */
export default function NowPlaying({ tracks, big = false }: { tracks: PublicTrack[]; big?: boolean }) {
  const player = usePlayer();
  const preview = tracks[0];
  const track = player.current ?? (preview ? toPlayable(preview) : null);
  if (!track) return null;

  const isLive = player.current?.asset_id === track.asset_id;
  const playing = isLive && player.playing;
  const progress = isLive ? player.progress : 0;
  const position = isLive ? player.position : 0;
  const duration = isLive ? player.duration : track.duration || 0;
  const token = track.url.split("token=")[1];
  const likeCount = preview && preview.asset_id === track.asset_id ? preview.like_count : undefined;

  const toggle = () => {
    if (isLive) player.toggle();
    else player.play(track);
  };

  return (
    <div className={`nowplaying card${big ? " nowplaying-big" : ""}`}>
      <div className="np-main">
        <ArtworkTile seed={track.asset_id} size={big ? 150 : 96} onPlay={toggle} />
        <div className="np-id">
          <div className="np-title">{track.title}</div>
          <div className="np-meta">
            {track.subtitle} · {fmtTime(duration)}
          </div>
          <div className="np-actions">
            <span className="np-like" title="Favorites">♥ {likeCount ?? 0}</span>
            <button
              className="btn btn-ghost"
              onClick={() => {
                const link = `${window.location.origin}/track/${track.asset_id}`;
                navigator.clipboard
                  ?.writeText(link)
                  .then(() => toast("Link copied to clipboard"))
                  .catch(() => toast(link));
              }}
            >
              Share
            </button>
          </div>
        </div>
        <div className="np-player">
          <button className={`np-play${playing ? " on" : ""}`} onClick={toggle} aria-label={playing ? "Pause" : "Play"}>
            {playing ? "❚❚" : "▶"}
          </button>
          <div style={{ flex: 1, minWidth: 60 }}>
            <Waveform
              assetId={track.asset_id}
              token={token}
              progress={progress}
              onSeek={(r) => {
                if (!isLive) player.play(track);
                setTimeout(() => player.seek(r), 60);
              }}
              height={big ? 56 : 40}
            />
          </div>
          <span className="np-time mono">
            {fmtTime(position)} / {fmtTime(duration)}
          </span>
          <input
            type="range"
            min={0}
            max={1}
            step={0.05}
            value={player.volume}
            onChange={(e) => player.setVolume(Number(e.target.value))}
            style={{ width: 90 }}
            aria-label="Volume"
          />
        </div>
      </div>
      <div className="np-export">
        <div className="np-export-title">Export</div>
        <div className="np-export-btns">
          <a className="btn" href={track.url} download>⇊ WAV</a>
          <button className="btn" onClick={() => exportArtifact(track.asset_id, "mp3")}>♫ MP3</button>
          <button className="btn" onClick={() => exportArtifact(track.asset_id, "stems")}>≋ WAV Stems</button>
        </div>
      </div>
    </div>
  );
}
