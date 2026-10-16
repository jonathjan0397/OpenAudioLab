import { useEffect, useState } from "react";
import { NavLink, Route, Routes } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api, SiteInfo } from "./api";
import AuthMenu from "./components/AuthMenu";
import { PlayerBar, PlayerProvider } from "./components/PlayerContext";
import { ThemeCtx } from "./theme";
import MainPage from "./pages/Main";
import StudioPage from "./pages/Studio";
import AdminPage from "./pages/Admin";
import ArtistPage from "./pages/Artist";

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
          <NavLink to="/artists">Explore</NavLink>
          <NavLink to="/studio">Studio</NavLink>
          <NavLink to="/admin">Admin</NavLink>
        </nav>
        <span className="spacer" />
        <span className="header-search">
          <span aria-hidden>⌕</span>
          <input placeholder="Search tracks, artists, prompts…" />
        </span>
        <span className="bell" title="Notifications">
          🔔<span className="dot" />
        </span>
        <AuthMenu />
        <select
          style={{ width: 150 }}
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
        <Route path="/" element={<MainPage theme={theme} />} />
        <Route path="/studio" element={<StudioPage />} />
        <Route path="/admin" element={<AdminPage />} />
        <Route path="/artists" element={<ArtistPage />} />
        <Route path="/artists/:slug" element={<ArtistPage />} />
      </Routes>
      <PlayerBar />
    </PlayerProvider>
    </ThemeCtx.Provider>
  );
}
