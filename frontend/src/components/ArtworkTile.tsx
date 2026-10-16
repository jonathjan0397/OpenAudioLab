import { useMemo } from "react";

function hash(str: string): number {
  let h = 2166136261;
  for (let i = 0; i < str.length; i++) {
    h ^= str.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

export default function ArtworkTile({
  seed,
  size = 56,
  duration,
  onPlay,
  wide,
}: {
  seed: string;
  size?: number;
  duration?: number | null;
  onPlay?: () => void;
  wide?: boolean;
}) {
  const { hue, hue2, bars } = useMemo(() => {
    const h = hash(seed);
    const hue = h % 360;
    const hue2 = (hue + 40 + (h >> 8) % 80) % 360;
    const bars: number[] = [];
    let x = h;
    for (let i = 0; i < 22; i++) {
      x = Math.imul(x ^ (x >>> 7), 0x9e3779b1) >>> 0;
      bars.push(0.25 + ((x >>> 9) % 100) / 133);
    }
    return { hue, hue2, bars };
  }, [seed]);

  return (
    <div
      className="art-tile"
      style={{
        width: wide ? "100%" : size,
        height: wide ? undefined : size,
        aspectRatio: wide ? "1.35" : undefined,
        background: `linear-gradient(${135 + (hue % 60)}deg, hsl(${hue} 72% 46%), hsl(${hue2} 78% 30%))`,
      }}
    >
      <svg className="motif" viewBox="0 0 100 100" preserveAspectRatio="none">
        {bars.map((b, i) => (
          <rect
            key={i}
            x={2 + i * 4.4}
            width={2.6}
            y={50 - b * 46}
            height={b * 92}
            rx={1.2}
            fill={`hsl(${hue2} 90% ${78 - b * 20}%)`}
            opacity={0.85}
          />
        ))}
      </svg>
      {onPlay && (
        <button className="play" onClick={onPlay} aria-label="Play">
          ▶
        </button>
      )}
      {duration != null && <span className="dur">{Math.floor(duration / 60)}:{Math.round(duration % 60).toString().padStart(2, "0")}</span>}
    </div>
  );
}
