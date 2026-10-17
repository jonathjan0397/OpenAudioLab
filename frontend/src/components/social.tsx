import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import { toast } from "./Toast";

export interface PublicArtist {
  name: string;
  slug: string;
}

export function usePublicArtists() {
  return useQuery({
    queryKey: ["public-artists"],
    queryFn: () => api.get<{ artists: PublicArtist[] }>("/api/v1/public/artists"),
    retry: false,
  });
}

export function FollowButton({ slug }: { slug?: string | null }) {
  const qc = useQueryClient();
  const follow = useMutation({
    mutationFn: async (unfollow: boolean) => {
      const method = unfollow ? "DELETE" : "POST";
      const res = await fetch(`/api/v1/public/artists/${slug}/follow`, {
        method,
        headers: { "content-type": "application/json" },
        credentials: "include",
      });
      const body = await res.json();
      if (res.status === 401) {
        toast("Sign in to follow artists");
        throw new Error("auth");
      }
      if (!res.ok) {
        toast(body?.error?.message || "Could not follow");
        throw new Error(body?.error?.code || "error");
      }
      return body as { following: boolean; follower_count: number };
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["public-artists"] }),
  });
  const following = follow.data?.following;
  return (
    <button
      className="btn btn-sm"
      style={following ? { borderColor: "var(--accent)", color: "var(--accent)" } : undefined}
      disabled={!slug}
      onClick={() => follow.mutate(!!following)}
    >
      {following ? "Following" : "Follow"}
    </button>
  );
}

export async function exportArtifact(assetId: string | null, format: "mp3" | "stems") {
  if (!assetId) {
    toast("Nothing to export yet");
    return;
  }
  const res = await fetch(`/api/v1/artifacts/${assetId}/export`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    credentials: "include",
    body: JSON.stringify({ format }),
  });
  const body = await res.json();
  if (res.status === 401) toast("Sign in to export");
  else if (res.ok)
    toast(format === "mp3" ? "MP3 export queued — check Studio › Recent" : "Stem separation queued (~1 min) — check back in ≋ Stems");
  else toast(body?.error?.message || "Export failed");
}
