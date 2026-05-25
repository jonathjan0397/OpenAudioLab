import { Outlet, Link, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthProvider";

export default function Layout() {
  const { user, logout, isAuthenticated } = useAuth();
  const navigate = useNavigate();

  const handleLogout = () => {
    logout();
    navigate("/login");
  };

  if (!isAuthenticated) {
    return <Outlet />;
  }

  return (
    <div style={{ minHeight: "100vh", display: "flex", flexDirection: "column" }}>
      <nav style={{ background: "#1a1a2e", color: "#eee", padding: "12px 24px", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div style={{ display: "flex", gap: "20px", alignItems: "center" }}>
          <Link to="/dashboard" style={{ color: "#eee", textDecoration: "none", fontWeight: "bold", fontSize: "18px" }}>OpenAudiolab</Link>
          <Link to="/dashboard" style={{ color: "#aaa", textDecoration: "none" }}>Dashboard</Link>
          <Link to="/jobs/new" style={{ color: "#aaa", textDecoration: "none" }}>Create Job</Link>
          <Link to="/agents" style={{ color: "#aaa", textDecoration: "none" }}>Agents</Link>
          <Link to="/system" style={{ color: "#aaa", textDecoration: "none" }}>System</Link>
          <Link to="/settings" style={{ color: "#aaa", textDecoration: "none" }}>Settings</Link>
        </div>
        <div style={{ display: "flex", gap: "12px", alignItems: "center" }}>
          <span style={{ color: "#888", fontSize: "14px" }}>{user?.email}</span>
          <button onClick={handleLogout} style={{ background: "#e74c3c", color: "#fff", border: "none", padding: "6px 16px", borderRadius: "4px", cursor: "pointer" }}>Logout</button>
        </div>
      </nav>
      <main style={{ flex: 1, padding: "24px", background: "#f5f5f5" }}>
        <Outlet />
      </main>
    </div>
  );
}
