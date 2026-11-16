import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, setCsrfToken, setUnauthenticatedHandler, type Role, type Session } from "./api";

interface AuthState {
  session: Session | null;
  loading: boolean;
  signIn: (username: string, password: string) => Promise<void>;
  signOut: () => Promise<void>;
  has: (role: Role) => boolean;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [loading, setLoading] = useState(true);

  const apply = useCallback((next: Session | null) => {
    setCsrfToken(next?.csrf_token ?? null);
    setSession(next);
  }, []);

  useEffect(() => {
    setUnauthenticatedHandler(() => apply(null));
    api
      .get<Session>("/session")
      .then(apply)
      .catch(() => apply(null))
      .finally(() => setLoading(false));
  }, [apply]);

  const value = useMemo<AuthState>(
    () => ({
      session,
      loading,
      signIn: async (username, password) => {
        apply(await api.post<Session>("/auth/login", { username, password }));
      },
      signOut: async () => {
        await api.post("/auth/logout").catch(() => undefined);
        apply(null);
      },
      has: (role) => session?.roles.includes(role) ?? false,
    }),
    [session, loading, apply],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth outside AuthProvider");
  return ctx;
}
