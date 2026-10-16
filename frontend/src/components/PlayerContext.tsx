import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  ReactNode,
} from "react";
import ArtworkTile from "./ArtworkTile";
import Waveform from "./Waveform";
import { fmtTime } from "./ui";

export interface Playable {
  asset_id: string;
  title: string;
  url: string;
  duration?: number | null;
  subtitle?: string;
}

interface PlayerState {
  current: Playable | null;
  playing: boolean;
  progress: number;
  position: number;
  duration: number;
  volume: number;
  play: (track: Playable) => void;
  toggle: () => void;
  seek: (ratio: number) => void;
  setVolume: (v: number) => void;
}

const Ctx = createContext<PlayerState | null>(null);

export function PlayerProvider({ children }: { children: ReactNode }) {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  if (audioRef.current === null && typeof Audio !== "undefined") {
    audioRef.current = new Audio();
  }
  const [current, setCurrent] = useState<Playable | null>(null);
  const [playing, setPlaying] = useState(false);
  const [position, setPosition] = useState(0);
  const [duration, setDuration] = useState(0);
  const [volume, setVolumeState] = useState(() => Number(localStorage.getItem("oal-volume") ?? 1));

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;
    const onTime = () => setPosition(audio.currentTime);
    const onMeta = () => setDuration(audio.duration || 0);
    const onEnd = () => setPlaying(false);
    audio.addEventListener("timeupdate", onTime);
    audio.addEventListener("loadedmetadata", onMeta);
    audio.addEventListener("ended", onEnd);
    return () => {
      audio.removeEventListener("timeupdate", onTime);
      audio.removeEventListener("loadedmetadata", onMeta);
      audio.removeEventListener("ended", onEnd);
    };
  }, []);

  useEffect(() => {
    if (audioRef.current) audioRef.current.volume = volume;
  }, [volume]);

  const play = useCallback((track: Playable) => {
    const audio = audioRef.current;
    if (!audio) return;
    if (current?.asset_id !== track.asset_id) {
      audio.src = track.url;
      setCurrent(track);
      setPosition(0);
      setDuration(track.duration || 0);
    }
    void audio.play().then(() => setPlaying(true)).catch(() => setPlaying(false));
  }, [current]);

  const toggle = useCallback(() => {
    const audio = audioRef.current;
    if (!audio || !current) return;
    if (audio.paused) void audio.play().then(() => setPlaying(true)).catch(() => {});
    else {
      audio.pause();
      setPlaying(false);
    }
  }, [current]);

  const seek = useCallback((ratio: number) => {
    const audio = audioRef.current;
    if (!audio || !isFinite(audio.duration)) return;
    audio.currentTime = ratio * audio.duration;
    setPosition(audio.currentTime);
  }, []);

  const setVolume = useCallback((v: number) => {
    setVolumeState(v);
    localStorage.setItem("oal-volume", String(v));
  }, []);

  const value = useMemo<PlayerState>(
    () => ({
      current,
      playing,
      progress: duration > 0 ? position / duration : 0,
      position,
      duration,
      volume,
      play,
      toggle,
      seek,
      setVolume,
    }),
    [current, playing, position, duration, volume, play, toggle, seek, setVolume]
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function usePlayer(): PlayerState {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("usePlayer outside provider");
  return ctx;
}

export function PlayerBar() {
  const p = usePlayer();
  if (!p.current) return null;
  return (
    <div className="player-bar">
      <div className="now">
        <ArtworkTile seed={p.current.asset_id} size={44} />
        <div style={{ minWidth: 0 }}>
          <div className="t">{p.current.title}</div>
          <div className="s">{p.current.subtitle || "OpenAudioLab"}</div>
        </div>
      </div>
      <div className="transport">
        <button className="btn btn-icon btn-ghost" onClick={p.toggle} aria-label={p.playing ? "Pause" : "Play"}>
          {p.playing ? "❚❚" : "▶"}
        </button>
      </div>
      <div className="seek">
        <span className="time">{fmtTime(p.position)}</span>
        <div style={{ flex: 1 }}>
          <Waveform assetId={p.current.asset_id} token={p.current.url.split("token=")[1]} progress={p.progress} onSeek={p.seek} height={34} />
        </div>
        <span className="time">{fmtTime(p.duration)}</span>
      </div>
      <input
        className="vol"
        type="range"
        min={0}
        max={1}
        step={0.05}
        value={p.volume}
        onChange={(e) => p.setVolume(Number(e.target.value))}
        aria-label="Volume"
      />
    </div>
  );
}
