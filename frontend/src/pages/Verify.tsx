import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { api, AuthUser } from "../api";

export default function VerifyPage() {
  const [params] = useSearchParams();
  const qc = useQueryClient();
  const [status, setStatus] = useState("Verifying…");

  useEffect(() => {
    const token = params.get("token");
    if (!token) {
      setStatus("Verification link is missing a token.");
      return;
    }
    api
      .post<{ user: AuthUser }>("/api/v1/auth/verify/confirm", { token })
      .then(() => {
        setStatus(`Verified for ${token.slice(0, 6)}…`);
        qc.invalidateQueries({ queryKey: ["me"] });
      })
      .catch((e: Error) => setStatus(e.message));
  }, [params, qc]);

  return (
    <div className="page">
      <div className="card" style={{ maxWidth: 520, margin: "0 auto" }}>
        <h1>Email verification</h1>
        <p>{status}</p>
      </div>
    </div>
  );
}
