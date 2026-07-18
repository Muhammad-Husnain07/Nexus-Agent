import axios from "axios"
import type { AuthStore } from "@/features/auth/authStore"

let _getAuth: (() => AuthStore) | null = null

export function injectAuth(getAuth: () => AuthStore) {
  _getAuth = getAuth
}

const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL || "http://localhost:8000/api/v1",
  headers: { "Content-Type": "application/json" },
})

api.interceptors.request.use((config) => {
  const auth = _getAuth?.()
  if (auth?.access_token) {
    config.headers.Authorization = `Bearer ${auth.access_token}`
  }
  if (auth?.tenant_id) {
    config.headers["X-Tenant-ID"] = auth.tenant_id
  }
  return config
})

api.interceptors.response.use(
  (response) => response,
  async (error) => {
    if (error.response?.status === 401) {
      const auth = _getAuth?.()
      if (auth?.refresh_token) {
        try {
          const { data } = await axios.post(
            `${api.defaults.baseURL}/auth/refresh`,
            { refresh_token: auth.refresh_token },
          )
          auth.setAccessToken(data.access_token)
          error.config.headers.Authorization = `Bearer ${data.access_token}`
          return api(error.config)
        } catch {
          auth.logout()
          window.location.href = "/login"
        }
      } else {
        auth?.logout()
        window.location.href = "/login"
      }
    }
    const message =
      error.response?.data?.detail || error.response?.data?.message || error.message || "An unexpected error occurred"
    return Promise.reject(new Error(message))
  },
)

export default api
