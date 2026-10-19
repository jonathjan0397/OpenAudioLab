import { createContext, useContext } from "react";

export const ThemeCtx = createContext("open-canvas");
export const useTheme = () => useContext(ThemeCtx);

const TILE_COUNT: Record<string, number> = {
  "open-canvas": 5,
  "neon-studio": 3,
  "analog-soul": 6,
  "signal-lab": 3,
};

function hash(str: string): number {
  let h = 2166136261;
  for (let i = 0; i < str.length; i++) {
    h ^= str.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

/** Deterministic theme-matched album art for a track id. */
export function themeArt(theme: string, seed: string): string {
  const n = TILE_COUNT[theme] || 3;
  const i = hash(seed) % n;
  if (theme === "signal-lab") {
    return i === 0 ? `/themes/${theme}/art/player.png` : `/themes/${theme}/art/v${i - 1}.png`;
  }
  return `/themes/${theme}/art/t${i}.png`;
}

export function themeAvatar(theme: string): string {
  return theme === "neon-studio" ? `/themes/${theme}/art/t0.png` : `/themes/${theme}/art/avatar.png`;
}

export function themeBanner(theme: string): string {
  return theme === "neon-studio" ? `/themes/${theme}/art/banner.png` : `/themes/${theme}/hero.png`;
}
