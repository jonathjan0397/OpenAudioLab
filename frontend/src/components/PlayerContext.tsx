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
  queue: Playable[];
  index: number;
  playing: boolean;
  shuffle: boolean;
  repeat: boolean;
  progress: number;
  position: number;
  duration: number;
  volume: number;
  play: (track: Playable) => void;
  playQueue: (tracks: Playable[], startIndex?: number) => void;
  toggle: () => void;
  next: () => void;
  prev: () => void;
  toggleShuffle: () => void;
  toggleRepeat: () => void;
  seek: (ratio: number) => void;
  setVolume: (v: number) => void;
}

const Ctx = createContext<PlayerState | null>(null);

export function PlayerProvider({ children }: { children: ReactNode }) {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  if (audioRef.current === null && typeof Audio !== "undefined") {
    audioRef.current = new Audio();
  }
  const [queue, setQueue] = useState<Playable[]>([]);
  const [index, setIndex] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [shuffle, setShuffle] = useState(false);
  const [repeat, setRepeat] = useState(false);
  const [position, setPosition] = useState(0);
  const [duration, setDuration] = useState(0);
  const [volume, setVolumeState] = useState(() => Number(localStorage.getItem("oal-volume") ?? 1));
  const repeatRef = useRef(repeat);
  repeatRef.current = repeat;

  const current = queue[index] ?? null;

  const load = useCallback((track: Playable, autoplay = true) => {
    const audio = audioRef.current;
    if (!audio) return;
    audio.src = track.url;
    setPosition(0);
    setDuration(track.duration || 0);
    void fetch(`/api/v1/artifacts/${track.asset_id}/play`, { method: "POST", credentials: "include" }).catch(() => {});
    if (autoplay) void audio.play().then(() => setPlaying(true)).catch(() => setPlaying(false));
  }, []);

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;
    const onTime = () => setPosition(audio.currentTime);
    const onMeta = () => setDuration(audio.duration || 0);
    const onEnd = () => {
      if (repeatRef.current) {
        audio.currentTime = 0;
        void audio.play();
        return;
      }
      setPlaying(false);
      window.dispatchEvent(new CustomEvent("oal:track-end"));
    };
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

  const play = useCallback(
    (track: Playable) => {
      if (current?.asset_id === track.asset_id) {
        const audio = audioRef.current;
        if (audio && audio.paused) void audio.play().then(() => setPlaying(true)).catch(() => {});
        return;
      }
      setQueue([track]);
      setIndex(0);
      load(track);
    },
    [current, load]
  );

  const playQueue = useCallback(
    (tracks: Playable[], startIndex = 0) => {
      setQueue(tracks);
      setIndex(startIndex);
      if (tracks[startIndex]) load(tracks[startIndex]);
    },
    [load]
  );

  const step = useCallback(
    (dir: 1 | -1) => {
      if (queue.length === 0) return;
      let nextIndex: number;
      if (shuffle && queue.length > 1) {
        do {
          nextIndex = Math.floor(Math.random() * queue.length);
        } while (nextIndex === index);
      } else {
        nextIndex = (index + dir + queue.length) % queue.length;
      }
      setIndex(nextIndex);
      load(queue[nextIndex]);
    },
    [queue, index, shuffle, load]
  );

  const next = useCallback(() => step(1), [step]);
  const prev = useCallback(() => step(-1), [step]);

  // auto-advance on track end
  useEffect(() => {
    const onEnd = () => {
      if (queue.length > 1) next();
    };
    window.addEventListener("oal:track-end", onEnd);
    return () => window.removeEventListener("oal:track-end", onEnd);
  }, [next, queue.length]);

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
      queue,
      index,
      playing,
      shuffle,
      repeat,
      progress: duration > 0 ? position / duration : 0,
      position,
      duration,
      volume,
      play,
      playQueue,
      toggle,
      next,
      prev,
      toggleShuffle: () => setShuffle((s) => !s),
      toggleRepeat: () => setRepeat((r) => !r),
      seek,
      setVolume,
    }),
    [current, queue, index, playing, shuffle, repeat, position, duration, volume, play, playQueue, toggle, next, prev, seek, setVolume]
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
  const [showQueue, setShowQueue] = useState(false);
  const barRef = useRef<HTMLDivElement>(null);
  if (!p.current) return null;

  const fullscreen = () => {
    const el = barRef.current;
    if (!el) return;
    if (document.fullscreenElement) void document.exitFullscreen();
    else void el.requestFullscreen?.();
  };

  return (
    <div className="player-bar" ref={barRef}>
      <div className="now">
        <ArtworkTile seed={p.current.asset_id} size={44} />
        <div style={{ minWidth: 0 }}>
          <div className="t">{p.current.title}</div>
          <div className="s">{p.current.subtitle || "OpenAudioLab"}</div>
        </div>
      </div>
      <div className="transport">
        <button className={`btn btn-icon btn-ghost${p.shuffle ? " on" : ""}`} onClick={p.toggleShuffle} title="Shuffle">⤨</button>
        <button className="btn btn-icon btn-ghost" onClick={p.prev} title="Previous">⏮</button>
        <button className="btn btn-icon btn-primary" onClick={p.toggle} aria-label={p.playing ? "Pause" : "Play"}>
          {p.playing ? "❚❚" : "▶"}
        </button>
        <button className="btn btn-icon btn-ghost" onClick={p.next} title="Next">⏭</button>
        <button className={`btn btn-icon btn-ghost${p.repeat ? " on" : ""}`} onClick={p.toggleRepeat} title="Repeat">⟳</button>
      </div>
      <div className="seek">
        <span className="time">{fmtTime(p.position)}</span>
        <div style={{ flex: 1 }}>
          <Waveform
            assetId={p.current.asset_id}
            token={p.current.url.split("token=")[1]}
            progress={p.progress}
            onSeek={p.seek}
            height={34}
          />
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
      <div style={{ position: "relative" }}>
        <button className="btn btn-icon btn-ghost" onClick={() => setShowQueue((s) => !s)} title="Queue">☰</button>
        {showQueue && (
          <div className="card queue-pop">
            {p.queue.map((t, i) => (
              <div
                key={t.asset_id + i}
                className={`queue-item${i === p.index ? " active" : ""}`}
                onClick={() => {
                  p.playQueue(p.queue, i);
                  setShowQueue(false);
                }}
              >
                <ArtworkTile seed={t.asset_id} size={28} />
                <span className="t">{t.title}</span>
              </div>
            ))}
          </div>
        )}
      </div>
      <button className="btn btn-icon btn-ghost" onClick={fullscreen} title="Fullscreen">⛶</button>
    </div>
  );
}
