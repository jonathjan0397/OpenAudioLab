import { useEffect, useState } from "react";
import { NavLink, Route, Routes } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api, SiteInfo } from "./api";
import AuthMenu from "./components/AuthMenu";
import MainPage from "./pages/Main";
import StudioPage from "./pages/Studio";
import AdminPage from "./pages/Admin";

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
    <>
      <header className="site-header">
        <span className="logo">OpenAudioLab.io</span>
        <nav>
          <NavLink to="/">Create</NavLink>
          <NavLink to="/studio">Studio</NavLink>
          <NavLink to="/admin">Admin</NavLink>
        </nav>
        <span className="spacer" />
        <AuthMenu />
        <select
          style={{ width: 160 }}
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
      </Routes>
    </>
  );
}
