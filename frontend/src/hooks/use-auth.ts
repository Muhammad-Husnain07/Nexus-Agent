import { create } from "zustand"
import { persist } from "zustand/middleware"

interface AuthState {
  token: string | null
  tenantId: string | null
  setAuth: (token: string, tenantId: string) => void
  logout: () => void
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      token: null,
      tenantId: null,
      setAuth: (token, tenantId) => set({ token, tenantId }),
      logout: () => set({ token: null, tenantId: null }),
    }),
    { name: "nexus-auth" },
  ),
)
