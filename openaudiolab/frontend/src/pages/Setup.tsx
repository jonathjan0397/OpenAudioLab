import { useState } from "react";
import { useNavigate } from "react-router-dom";
import api from "../api/client";

export default function Setup() {
  const navigate = useNavigate();
  const [form, setForm] = useState({
    admin_email: "",
    admin_password: "",
    confirm_password: "",
    site_name: "OpenAudiolab",
    public_backend_url: "http://localhost:8000",
    storage_provider: "local",
    default_retention_days: 7,
    enable_cpu_test_mode: true,
    enable_cloud_workers: false,
  });
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    if (form.admin_password !== form.confirm_password) {
      setError("Passwords do not match");
      return;
    }
    setLoading(true);
    try {
      await api.post("/api/setup/initialize", form);
      navigate("/login");
    } catch (err: any) {
      setError(err.response?.data?.detail || "Setup failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ maxWidth: "500px", margin: "60px auto", padding: "24px", background: "#fff", borderRadius: "8px", boxShadow: "0 2px 8px rgba(0,0,0,0.1)" }}>
      <h2 style={{ marginTop: 0 }}>OpenAudiolab Setup</h2>
      {error && <div style={{ background: "#fee", color: "#c00", padding: "8px", borderRadius: "4px", marginBottom: "16px" }}>{error}</div>}
      <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
        <label>Admin Email<input type="email" value={form.admin_email} onChange={(e) => setForm({ ...form, admin_email: e.target.value })} required style={{ width: "100%", padding: "8px", marginTop: "4px" }} /></label>
        <label>Admin Password (min 12 chars)<input type="password" value={form.admin_password} onChange={(e) => setForm({ ...form, admin_password: e.target.value })} required minLength={12} style={{ width: "100%", padding: "8px", marginTop: "4px" }} /></label>
        <label>Confirm Password<input type="password" value={form.confirm_password} onChange={(e) => setForm({ ...form, confirm_password: e.target.value })} required style={{ width: "100%", padding: "8px", marginTop: "4px" }} /></label>
        <label>Site Name<input type="text" value={form.site_name} onChange={(e) => setForm({ ...form, site_name: e.target.value })} required style={{ width: "100%", padding: "8px", marginTop: "4px" }} /></label>
        <label>Storage Provider
          <select value={form.storage_provider} onChange={(e) => setForm({ ...form, storage_provider: e.target.value })} style={{ width: "100%", padding: "8px", marginTop: "4px" }}>
            <option value="local">Local</option>
            <option value="minio">MinIO</option>
            <option value="s3_compatible">S3 Compatible</option>
          </select>
        </label>
        <label>Default Retention Days<input type="number" value={form.default_retention_days} onChange={(e) => setForm({ ...form, default_retention_days: parseInt(e.target.value) })} min={1} max={365} style={{ width: "100%", padding: "8px", marginTop: "4px" }} /></label>
        <label><input type="checkbox" checked={form.enable_cpu_test_mode} onChange={(e) => setForm({ ...form, enable_cpu_test_mode: e.target.checked })} /> Enable CPU Test Mode</label>
        <label><input type="checkbox" checked={form.enable_cloud_workers} onChange={(e) => setForm({ ...form, enable_cloud_workers: e.target.checked })} /> Enable Cloud Workers</label>
        <button type="submit" disabled={loading} style={{ background: "#27ae60", color: "#fff", border: "none", padding: "12px", borderRadius: "4px", cursor: "pointer", fontSize: "16px" }}>
          {loading ? "Setting up..." : "Complete Setup"}
        </button>
      </form>
    </div>
  );
}
