import React, { createContext, useContext, useState, useEffect } from "react";
import api from "../api/client";

interface User {
  id: string;
  email: string;
  is_admin: boolean;
}

interface AuthContextType {
  user: User | null;
  token: string | null;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
  isAuthenticated: boolean;
}

const AuthContext = createContext<AuthContextType | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [token, setToken] = useState<string | null>(localStorage.getItem("token"));

  useEffect(() => {
    if (token) {
      api.get("/api/auth/me").then((res) => setUser(res.data)).catch(() => {
        localStorage.removeItem("token");
        setToken(null);
      });
    }
  }, [token]);

  const login = async (email: string, password: string) => {
    const res = await api.post("/api/auth/login", { email, password });
    setToken(res.data.access_token);
    setUser(res.data.user);
    localStorage.setItem("token", res.data.access_token);
  };

  const logout = () => {
    setToken(null);
    setUser(null);
    localStorage.removeItem("token");
  };

  return (
    <AuthContext.Provider value={{ user, token, login, logout, isAuthenticated: !!token }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
