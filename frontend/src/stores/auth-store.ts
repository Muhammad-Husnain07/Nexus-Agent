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
      const partial = {
        user: data.user,
        access_token: data.access_token,
        refresh_token: data.refresh_token,
        isAuthenticated: true,
        selectedTenantId: data.user.tenant_id,
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
      const res = await fetch("/api/v1/auth/refresh", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token }),
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
