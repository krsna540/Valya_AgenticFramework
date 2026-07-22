import { createContext, useContext, useEffect, useState, ReactNode } from "react";
import { api, clearToken, getToken, setToken } from "../api/client";
import type { AuthResponse, User } from "../types";

interface AuthContextValue {
  user: User | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  signup: (email: string, fullName: string, password: string, tenantName?: string) => Promise<void>;
  // One-time only — POST /auth/bootstrap-super-admin 404s once a
  // super_admin row already exists (see docs/AUTHORIZATION.md). Callers
  // should treat a 404 here as "already bootstrapped", not "not found".
  bootstrapSuperAdmin: (email: string, fullName: string, password: string) => Promise<void>;
  logout: () => void;
  refreshUser: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const token = getToken();
    if (!token) {
      setLoading(false);
      return;
    }
    api
      .get<User>("/auth/me")
      .then(setUser)
      .catch(() => clearToken())
      .finally(() => setLoading(false));
  }, []);

  async function login(email: string, password: string) {
    const form = new URLSearchParams();
    form.set("username", email);
    form.set("password", password);
    const res = await api.postForm<AuthResponse>("/auth/login", form);
    setToken(res.access_token);
    setUser(res.user);
  }

  async function signup(email: string, fullName: string, password: string, tenantName?: string) {
    const res = await api.post<AuthResponse>("/auth/signup", {
      email,
      full_name: fullName,
      password,
      tenant_name: tenantName || undefined,
    });
    setToken(res.access_token);
    setUser(res.user);
  }

  async function bootstrapSuperAdmin(email: string, fullName: string, password: string) {
    const res = await api.post<AuthResponse>("/auth/bootstrap-super-admin", {
      email,
      full_name: fullName,
      password,
    });
    setToken(res.access_token);
    setUser(res.user);
  }

  function logout() {
    clearToken();
    setUser(null);
  }

  async function refreshUser() {
    try {
      setUser(await api.get<User>("/auth/me"));
    } catch {
      // ignore — caller can retry
    }
  }

  return (
    <AuthContext.Provider value={{ user, loading, login, signup, bootstrapSuperAdmin, logout, refreshUser }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
