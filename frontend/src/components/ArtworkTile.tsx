import { themeArt, useTheme } from "../theme";

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
  const theme = useTheme();
  return (
    <div
      className="art-tile"
      style={{
        width: wide ? "100%" : size,
        height: wide ? undefined : size,
        aspectRatio: wide ? "1.35" : undefined,
      }}
    >
      <img className="art-photo" src={themeArt(theme, seed)} alt="" loading="lazy" />
      {onPlay && (
        <button className="play" onClick={onPlay} aria-label="Play">
          ▶
        </button>
      )}
      {duration != null && (
        <span className="dur">
          {Math.floor(duration / 60)}:{Math.round(duration % 60).toString().padStart(2, "0")}
        </span>
      )}
    </div>
  );
}
