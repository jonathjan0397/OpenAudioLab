import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { Playable } from "./PlayerContext";

export interface PublicTrack {
  asset_id: string;
  title: string;
  slug?: string | null;
  duration_seconds: number | null;
  created_at: string | null;
  like_count: number;
  plays?: number;
  favorite?: boolean;
  tags?: string[];
  creator: string;
  url: string;
}

export interface ArtistStats {
  name: string;
  slug: string | null;
  tracks: number;
  followers: number;
  plays: number;
}

export function usePublicTracks(limit = 12, tag?: string, mode = "recent") {
  return useQuery({
    queryKey: ["public-tracks", limit, tag || "", mode],
    queryFn: () =>
      api.get<{ tracks: PublicTrack[] }>(
        `/api/v1/public/tracks?limit=${limit}&mode=${encodeURIComponent(mode)}${tag ? `&tag=${encodeURIComponent(tag)}` : ""}`
      ),
  });
}

export function useSpotlight() {
  return useQuery({
    queryKey: ["spotlight"],
    queryFn: () => api.get<{ artist: ArtistStats | null }>("/api/v1/public/spotlight"),
    staleTime: 60000,
  });
}

export function useArtistStats(slug: string | null | undefined) {
  return useQuery({
    queryKey: ["artist-stats", slug],
    queryFn: () => api.get<ArtistStats>(`/api/v1/public/artists/${slug}/stats`),
    enabled: !!slug,
    retry: false,
  });
}

export function fmtCount(n: number | undefined): string {
  if (n == null) return "0";
  if (n >= 1e6) return `${(n / 1e6).toFixed(1)}M`;
  if (n >= 1e3) return `${(n / 1e3).toFixed(1)}K`;
  return String(n);
}

export function toPlayable(t: PublicTrack, subtitle?: string): Playable {
  return {
    asset_id: t.asset_id,
    title: t.title || "Untitled",
    url: t.url,
    duration: t.duration_seconds,
    subtitle: subtitle || t.creator,
  };
}
