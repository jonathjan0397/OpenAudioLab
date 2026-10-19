import { useQuery } from "@tanstack/react-query";
import { api, PolicyPayload } from "../api";

export default function PoliciesPage() {
  const policies = useQuery({
    queryKey: ["policies"],
    queryFn: () => api.get<PolicyPayload>("/api/v1/policies"),
  });

  return (
    <div className="page">
      <div className="card" style={{ maxWidth: 760, margin: "0 auto" }}>
        <h1>Policies</h1>
        <p className="sub">
          Current version: <strong>{policies.data?.version || "…"}</strong>
        </p>
        <p className="sub">
          Operator: {policies.data?.operator || "OpenAudioLab"} ·{" "}
          <a className="link" href={policies.data?.support_url || "/pricing"}>
            Support
          </a>
        </p>
        <ul>
          {(policies.data?.documents || []).map((doc) => (
            <li key={doc.id}>
              {doc.name} <span className="sub">({doc.version})</span>
            </li>
          ))}
        </ul>
        <p className="sub">
          Guests can generate up to four songs per UTC day, with a two-minute maximum duration. Account signup requires
          acceptance of the Terms, Abuse Policy, and Privacy Notice.
        </p>
      </div>
    </div>
  );
}
