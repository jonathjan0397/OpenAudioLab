import { createContext, ReactNode, useCallback, useContext } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, AuthUser } from "../api";

export interface WorkspaceRow {
  workspace_id: string;
  name: string;
  is_default: boolean;
  song_count?: number;
  asset_count?: number;
}

interface ActiveResp {
  workspace_id: string;
  is_default: boolean;
}

interface WorkspaceValue {
  activeId: string | null;
  isDefault: boolean;
  workspaces: WorkspaceRow[];
  setActive: (id: string | null) => void;
}

const WorkspaceCtx = createContext<WorkspaceValue>({
  activeId: null,
  isDefault: true,
  workspaces: [],
  setActive: () => {},
});

export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const me = useQuery({
    queryKey: ["me"],
    queryFn: () => api.get<{ user: AuthUser }>("/api/v1/auth/me"),
    retry: false,
  });
  const loggedIn = !!me.data?.user;
  const active = useQuery({
    queryKey: ["workspaces-active"],
    queryFn: () => api.get<ActiveResp>("/api/v1/workspaces/active"),
    enabled: loggedIn,
    retry: false,
  });
  const spaces = useQuery({
    queryKey: ["workspaces"],
    queryFn: () => api.get<{ workspaces: WorkspaceRow[] }>("/api/v1/workspaces"),
    enabled: loggedIn,
    retry: false,
  });

  const setActive = useCallback(
    (id: string | null) => {
      if (!loggedIn) return;
      api
        .post<ActiveResp>("/api/v1/workspaces/active", { workspace_id: id })
        .then((res) => qc.setQueryData<ActiveResp>(["workspaces-active"], res))
        .catch(() => qc.invalidateQueries({ queryKey: ["workspaces-active"] }))
        .finally(() => {
          qc.invalidateQueries({ queryKey: ["my-tracks"] });
          qc.invalidateQueries({ queryKey: ["me"] });
        });
    },
    [loggedIn, qc]
  );

  return (
    <WorkspaceCtx.Provider
      value={{
        activeId: loggedIn ? active.data?.workspace_id ?? null : null,
        isDefault: active.data?.is_default ?? true,
        workspaces: spaces.data?.workspaces ?? [],
        setActive,
      }}
    >
      {children}
    </WorkspaceCtx.Provider>
  );
}

export function useWorkspace(): WorkspaceValue {
  return useContext(WorkspaceCtx);
}
