import { useEffect, useRef, useState } from "react";
import { NavLink, Route, Routes, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api, SiteInfo } from "./api";
import AuthMenu from "./components/AuthMenu";
import { PlayerBar, PlayerProvider } from "./components/PlayerContext";
import Toaster from "./components/Toast";
import { ThemeCtx } from "./theme";
import MainPage from "./pages/Main";
import StudioPage from "./pages/Studio";
import AdminPage from "./pages/Admin";
import ArtistPage from "./pages/Artist";
import ExplorePage from "./pages/Explore";
import PricingPage from "./pages/Pricing";
import SettingsPage from "./pages/Settings";
import TrainingPage from "./pages/Training";

const TEMPLATES = ["open-canvas", "analog-soul", "neon-studio", "signal-lab"];

export default function App() {
  const site = useQuery({
    queryKey: ["site"],
    queryFn: () => api.get<SiteInfo>("/api/v1/site"),
  });
  const [preview, setPreview] = useState<string | null>(
    () => window.localStorage.getItem("oal-theme-preview")
  );
  const theme = preview || site.data?.template || "open-canvas";
  const navigate = useNavigate();
  const searchRef = useRef<HTMLInputElement>(null);
  const [bellOpen, setBellOpen] = useState(false);
  const notes = useQuery({
    queryKey: ["notifications"],
    queryFn: () =>
      api.get<{ notifications: { job_id: string; status: string; title: string; created_at: string | null }[]; active_count: number }>(
        "/api/v1/notifications"
      ),
    retry: false,
    refetchInterval: 15000,
  });

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);

  return (
    <ThemeCtx.Provider value={theme}>
    <PlayerProvider>
      <header className="site-header">
        <span className="logo">
          OpenAudioLab<span className="tld">.io</span>
        </span>
        <span className="brand-tag">{theme.replace(/-/g, " ")}</span>
        <nav>
          <NavLink to="/" end>Create</NavLink>
          <NavLink to="/explore">Explore</NavLink>
          <NavLink to="/artists">Artists</NavLink>
          <NavLink to="/studio">Studio</NavLink>
          <NavLink to="/pricing">Pricing</NavLink>
          <NavLink to="/admin">Admin</NavLink>
        </nav>
        <span className="spacer" />
        <span className="header-search">
          <span aria-hidden>⌕</span>
          <input
            ref={searchRef}
            placeholder="Search tracks, artists, prompts…"
            onKeyDown={(e) => {
              if (e.key === "Enter" && searchRef.current?.value.trim()) {
                navigate(`/explore?q=${encodeURIComponent(searchRef.current.value.trim())}`);
              }
            }}
          />
        </span>
        <span className="spacer" />
        <span className="bell-wrap">
          <span className="bell" title="Notifications" onClick={() => setBellOpen((o) => !o)}>
            🔔{notes.data && notes.data.active_count > 0 && <span className="dot" />}
          </span>
          {bellOpen && (
            <div className="card bell-menu">
              <div className="card-header">
                <h3>Notifications</h3>
              </div>
              {(notes.data?.notifications || []).slice(0, 8).map((n) => (
                <div key={n.job_id} className="bell-item">
                  <span className={`status-pill ${["succeeded", "completed"].includes(n.status) ? "ok" : ["failed", "cancelled"].includes(n.status) ? "bad" : "wait"}`}>
                    {n.status}
                  </span>
                  <span className="bell-title">{n.title}</span>
                </div>
              ))}
              {(notes.data?.notifications || []).length === 0 && (
                <p style={{ color: "var(--muted)", fontSize: 13 }}>Nothing yet. Sign in to see your job activity.</p>
              )}
              <a className="link" href="/studio" onClick={() => setBellOpen(false)}>Open Studio →</a>
            </div>
          )}
        </span>
        <AuthMenu />
        <NavLink to="/studio" className="btn btn-primary btn-sm open-studio">Open Studio →</NavLink>
        <select
          className="theme-select"
          style={{ width: 130 }}
          value={theme}
          onChange={(e) => {
            window.localStorage.setItem("oal-theme-preview", e.target.value);
            setPreview(e.target.value);
          }}
        >
          {TEMPLATES.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
      </header>
      <Routes>
        <Route path="/" element={<MainPage />} />
        <Route path="/studio" element={<StudioPage />} />
        <Route path="/admin" element={<AdminPage />} />
        <Route path="/artists" element={<ArtistPage />} />
        <Route path="/artists/:slug" element={<ArtistPage />} />
        <Route path="/explore" element={<ExplorePage />} />
        <Route path="/pricing" element={<PricingPage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="/training" element={<TrainingPage />} />
      </Routes>
      <PlayerBar />
      <Toaster />
    </PlayerProvider>
    </ThemeCtx.Provider>
  );
}
