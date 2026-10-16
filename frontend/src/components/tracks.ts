import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { Playable } from "./PlayerContext";

export interface PublicTrack {
  asset_id: string;
  title: string | null;
  duration_seconds: number | null;
  created_at: string | null;
  like_count: number;
  creator: string;
  url: string;
}

export function usePublicTracks(limit = 12) {
  return useQuery({
    queryKey: ["public-tracks", limit],
    queryFn: () => api.get<{ tracks: PublicTrack[] }>(`/api/v1/public/tracks?limit=${limit}`),
  });
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
