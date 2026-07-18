import { create } from "zustand"
import { persist } from "zustand/middleware"

interface StoredUser {
  id: string
  email: string
  role: string
  tenant_id: string | null
}

export interface AuthStore {
  access_token: string | null
  refresh_token: string | null
  user: StoredUser | null
  tenant_id: string | null
  isAuthenticated: () => boolean
  setAccessToken: (token: string) => void
  setUser: (user: StoredUser) => void
  login: (access: string, refresh: string, user: StoredUser) => void
  logout: () => void
}

function decodeJWT(token: string): Record<string, unknown> | null {
  try {
    const payload = token.split(".")[1]
    return JSON.parse(atob(payload))
  } catch {
    return null
  }
}

export function decodeUserFromToken(token: string, email: string): StoredUser | null {
  const payload = decodeJWT(token)
  if (!payload) return null
  return {
    id: (payload.sub as string) || "",
    email,
    role: (payload.role as string) || "end_user",
    tenant_id: (payload.tid as string) || null,
  }
}

export const useAuthStore = create<AuthStore>()(
  persist(
    (set, get) => ({
      access_token: null,
      refresh_token: null,
      user: null,
      tenant_id: null,

      isAuthenticated: () => {
        const token = get().access_token
        if (!token) return false
        const payload = decodeJWT(token)
        if (!payload) return false
        const exp = payload.exp as number
        if (exp && Date.now() >= exp * 1000) return false
        return true
      },

      setAccessToken: (token: string) => {
        set({ access_token: token })
      },

      setUser: (user: StoredUser) => {
        set({ user, tenant_id: user.tenant_id })
      },

      login: (access: string, refresh: string, user: StoredUser) => {
        set({
          access_token: access,
          refresh_token: refresh,
          user,
          tenant_id: user.tenant_id,
        })
      },

      logout: () => {
        set({
          access_token: null,
          refresh_token: null,
          user: null,
          tenant_id: null,
        })
      },
    }),
    {
      name: "nexus-auth",
    },
  ),
)
