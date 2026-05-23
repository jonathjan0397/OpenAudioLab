import { useEffect, useState } from "react";
import api from "../api/client";
import WorkerCard from "../components/WorkerCard";

export default function Workers() {
  const [workers, setWorkers] = useState<any[]>([]);

  useEffect(() => {
    api.get("/api/workers").then((r) => setWorkers(r.data));
    const interval = setInterval(() => api.get("/api/workers").then((r) => setWorkers(r.data)), 10000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div>
      <h2>Workers</h2>
      {workers.length === 0 ? (
        <div style={{ color: "#666" }}>No workers registered.</div>
      ) : (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(300px, 1fr))", gap: "16px" }}>
          {workers.map((w) => <WorkerCard key={w.id} worker={w} />)}
        </div>
      )}
    </div>
  );
}
