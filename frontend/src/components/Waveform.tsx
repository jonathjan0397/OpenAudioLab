import { useEffect, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api";

interface Peaks {
  buckets: number;
  rate: number;
  duration_seconds: number;
  peaks: number[];
}

export function usePeaks(assetId: string | null, token?: string) {
  return useQuery({
    queryKey: ["peaks", assetId, token || ""],
    queryFn: () => api.get<Peaks>(`/api/v1/artifacts/${assetId}/waveform${token ? `?token=${token}` : ""}`),
    enabled: !!assetId,
    staleTime: Infinity,
    retry: 0,
  });
}

export default function Waveform({
  assetId,
  token,
  progress = 0,
  onSeek,
  height = 40,
}: {
  assetId: string | null;
  token?: string;
  progress?: number;
  onSeek?: (ratio: number) => void;
  height?: number;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const peaks = usePeaks(assetId, token);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const dpr = window.devicePixelRatio || 1;
    const w = canvas.clientWidth;
    const h = canvas.clientHeight;
    if (canvas.width !== w * dpr) {
      canvas.width = w * dpr;
      canvas.height = h * dpr;
    }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    const data = peaks.data?.peaks;
    const styles = getComputedStyle(document.documentElement);
    const accent = styles.getPropertyValue("--accent").trim() || "#f4511e";
    const idle = styles.getPropertyValue("--border").trim() || "#ccc";
    if (!data || data.length === 0) {
      // deterministic placeholder bars so the layout never looks broken
      ctx.fillStyle = idle;
      for (let i = 0; i < 60; i++) {
        const v = 0.2 + Math.abs(Math.sin(i * 12.9898)) * 0.55;
        ctx.fillRect(i * (w / 60) + 1, (h * (1 - v)) / 2, Math.max(1.5, w / 60 - 2), h * v);
      }
      return;
    }
    const bw = w / data.length;
    data.forEach((v, i) => {
      const bh = Math.max(2, v * h * 0.92);
      ctx.fillStyle = i / data.length <= progress ? accent : idle;
      ctx.fillRect(i * bw + bw * 0.15, (h - bh) / 2, Math.max(1, bw * 0.7), bh);
    });
  }, [peaks.data, progress, height]);

  return (
    <div
      className="waveform"
      style={{ height }}
      onClick={(e) => {
        if (!onSeek) return;
        const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
        onSeek(Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width)));
      }}
    >
      <canvas ref={canvasRef} />
    </div>
  );
}
