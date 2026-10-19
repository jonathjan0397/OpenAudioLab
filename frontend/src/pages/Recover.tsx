import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useMutation } from "@tanstack/react-query";
import { useQueryClient } from "@tanstack/react-query";
import { api, AuthUser } from "../api";

export default function RecoverPage() {
  const [params] = useSearchParams();
  const qc = useQueryClient();
  const token = params.get("token") || "";
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [status, setStatus] = useState(token ? "Enter a new password." : "Reset link is missing a token.");

  const reset = useMutation({
    mutationFn: () => api.post<{ user: AuthUser }>("/api/v1/auth/password/reset/confirm", { token, new_password: password }),
    onSuccess: () => {
      setStatus("Password updated.");
      qc.invalidateQueries({ queryKey: ["me"] });
    },
    onError: (e: Error) => setStatus(e.message),
  });

  return (
    <div className="page">
      <div className="card" style={{ maxWidth: 520, margin: "0 auto" }}>
        <h1>Password reset</h1>
        <p className="sub">{status}</p>
        {token && (
          <>
            <input type="password" placeholder="new password" value={password} onChange={(e) => setPassword(e.target.value)} />
            <input type="password" placeholder="confirm password" value={confirm} onChange={(e) => setConfirm(e.target.value)} />
            <button
              className="btn btn-primary"
              disabled={!token || password.length < 8 || password !== confirm || reset.isPending}
              onClick={() => reset.mutate()}
            >
              {reset.isPending ? "Saving…" : "Save password"}
            </button>
          </>
        )}
      </div>
    </div>
  );
}
