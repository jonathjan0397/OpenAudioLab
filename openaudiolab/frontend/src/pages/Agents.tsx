import { useEffect, useState } from "react";
import api from "../api/client";
import AgentCard from "../components/AgentCard";

export default function Agents() {
  const [agents, setAgents] = useState<any[]>([]);

  useEffect(() => {
    api.get("/api/agents").then((r) => setAgents(r.data));
    const interval = setInterval(() => api.get("/api/agents").then((r) => setAgents(r.data)), 10000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div>
      <h2>Agents</h2>
      {agents.length === 0 ? (
        <div style={{ color: "#666" }}>No agents registered.</div>
      ) : (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(300px, 1fr))", gap: "16px" }}>
          {agents.map((a) => <AgentCard key={a.id} agent={a} />)}
        </div>
      )}
    </div>
  );
}
