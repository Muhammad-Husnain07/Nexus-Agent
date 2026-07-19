import { create } from "zustand";

export interface User {
  id: string;
  email: string;
  role: "tenant_admin" | "developer" | "end_user" | "viewer";
  tenant_id: string;
}

interface AuthState {
  user: User | null;
  access_token: string | null;
  refresh_token: string | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  selectedTenantId: string | null;
  login: (email: string) => Promise<void>;
  logout: () => void;
  refreshToken: () => Promise<void>;
  setUser: (user: User) => void;
  setTokens: (access: string, refresh: string) => void;
  selectTenant: (tenantId: string) => void;
}

const STORAGE_KEY = "nexus-auth";

function loadPersisted() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) return JSON.parse(raw);
  } catch { /* ignore */ }
  return null;
}

function persistState(partial: Record<string, unknown>) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(partial));
  } catch { /* ignore */ }
}

function decodeJWT(token: string): Record<string, unknown> {
  try {
    const payload = token.split(".")[1];
    return JSON.parse(atob(payload));
  } catch {
    return {};
  }
}

function userFromToken(token: string): User | null {
  const claims = decodeJWT(token);
  const sub = claims.sub as string;
  const role = claims.role as string;
  const tid = claims.tid as string;
  if (!sub || !role || !tid) return null;
  return {
    id: sub,
    email: claims.email as string || sub,
    role: role as User["role"],
    tenant_id: tid,
  };
}

const persisted = loadPersisted();

export const useAuthStore = create<AuthState>()((set, get) => ({
  user: persisted?.user ?? null,
  access_token: persisted?.access_token ?? null,
  refresh_token: persisted?.refresh_token ?? null,
  isAuthenticated: persisted?.isAuthenticated ?? false,
  isLoading: false,
  selectedTenantId: persisted?.selectedTenantId ?? null,

  login: async (email: string) => {
    set({ isLoading: true });
    try {
      const res = await fetch("/api/v1/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email }),
      });
      if (!res.ok) throw new Error("Login failed");
      const data = await res.json();
      const token = data.access_token;
      const user = userFromToken(token);
      const partial = {
        user,
        access_token: token,
        refresh_token: data.refresh_token,
        isAuthenticated: true,
        selectedTenantId: user?.tenant_id || null,
      };
      set({ ...partial, isLoading: false });
      persistState(partial);
    } catch (e) {
      set({ isLoading: false });
      throw e;
    }
  },

  logout: () => {
    const partial = {
      user: null,
      access_token: null,
      refresh_token: null,
      isAuthenticated: false,
      selectedTenantId: null,
    };
    set(partial);
    persistState(partial);
  },

  refreshToken: async () => {
    const { refresh_token } = get();
    if (!refresh_token) return;
    try {
      const res = await fetch(`/api/v1/auth/refresh?refresh_token=${encodeURIComponent(refresh_token)}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
      });
      if (res.ok) {
        const data = await res.json();
        set({ access_token: data.access_token, refresh_token: data.refresh_token });
      } else {
        get().logout();
      }
    } catch {
      get().logout();
    }
  },

  setUser: (user) => set({ user }),
  setTokens: (access, refresh) => {
    set({ access_token: access, refresh_token: refresh });
    persistState({ access_token: access, refresh_token: refresh });
  },
  selectTenant: (tenantId) => {
    set({ selectedTenantId: tenantId });
    persistState({ selectedTenantId: tenantId });
  },
}));
