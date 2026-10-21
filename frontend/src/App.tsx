import { useEffect, useRef, useState } from "react";
import { NavLink, Route, Routes, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api, AuthUser, SiteInfo } from "./api";
import AuthMenu from "./components/AuthMenu";
import { PlayerBar, PlayerProvider } from "./components/PlayerContext";
import { WorkspaceProvider, useWorkspace } from "./components/WorkspaceContext";
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
import VoiceStudioPage from "./pages/VoiceStudio";
import TrackPage from "./pages/Track";
import StylesPage from "./pages/Styles";
import PoliciesPage from "./pages/Policies";
import FaqPage from "./pages/Faq";
import RecoverPage from "./pages/Recover";
import VerifyPage from "./pages/Verify";

export default function App() {
  const site = useQuery({
    queryKey: ["site"],
    queryFn: () => api.get<SiteInfo>("/api/v1/site"),
  });
  const me = useQuery({
    queryKey: ["me"],
    queryFn: () => api.get<{ user: AuthUser }>("/api/v1/auth/me"),
    retry: false,
  });
  const theme = site.data?.template || "open-canvas";
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
      <WorkspaceProvider>
      <header className="site-header">
        <NavLink to="/" className="logo">
          OpenAudioLab<span className="tld">.io</span>
        </NavLink>
        <nav>
          <NavLink to="/" end>Create</NavLink>
          <NavLink to="/explore">Explore</NavLink>
          <NavLink to="/artists">Artists</NavLink>
          <NavLink to="/studio">Studio</NavLink>
          <NavLink to="/pricing">Pricing</NavLink>
          <NavLink to="/faq">Help</NavLink>
          {me.data?.user?.role === "admin" && <NavLink to="/admin">Admin</NavLink>}
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
        <WorkspaceSwitcher />
        <AuthMenu />
      </header>
      <Routes>
        <Route path="/" element={<MainPage />} />
        <Route path="/studio" element={<StudioPage />} />
        <Route path="/admin/*" element={<AdminPage />} />
        <Route path="/artists" element={<ArtistPage />} />
        <Route path="/artists/:slug" element={<ArtistPage />} />
        <Route path="/explore" element={<ExplorePage />} />
        <Route path="/pricing" element={<PricingPage />} />
        <Route path="/styles" element={<StylesPage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="/training" element={<TrainingPage />} />
        <Route path="/voice" element={<VoiceStudioPage />} />
        <Route path="/track/:assetId" element={<TrackPage />} />
        <Route path="/policies" element={<PoliciesPage />} />
        <Route path="/faq" element={<FaqPage />} />
        <Route path="/verify" element={<VerifyPage />} />
        <Route path="/recover" element={<RecoverPage />} />
      </Routes>
      <footer className="site-footer">
        <span>{site.data?.operator || "OpenAudioLab"}</span>
        <a className="link" href="/policies">Terms</a>
        <a className="link" href="/policies">Abuse Policy</a>
        <a className="link" href="/policies">Privacy</a>
        <a className="link" href="/faq">Help / FAQ</a>
        <a className="link" href={site.data?.support_url || "/pricing"}>Support</a>
      </footer>
      <PlayerBar />
      <Toaster />
      </WorkspaceProvider>
    </PlayerProvider>
    </ThemeCtx.Provider>
  );
}

function WorkspaceSwitcher() {
  const { activeId, workspaces, setActive } = useWorkspace();
  if (workspaces.length === 0) return null;
  return (
    <span className="ws-switcher" title="Active workspace — new songs are saved here">
      <span aria-hidden>▤</span>
      <select
        value={activeId ?? ""}
        onChange={(e) => setActive(e.target.value || null)}
        aria-label="Active workspace"
      >
        {workspaces.map((w) => (
          <option key={w.workspace_id} value={w.workspace_id}>
            {w.is_default ? `★ ${w.name}` : w.name}
          </option>
        ))}
      </select>
    </span>
  );
}
