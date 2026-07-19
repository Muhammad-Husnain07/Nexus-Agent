import axios from "axios"

// Demo JWT token for the tenant_admin user (expires in 30 min)
const DEMO_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIwMDAwMDAwMC0wMDAwLTAwMDAtMDAwMC0wMDAwMDAwMDAwMDIiLCJyb2xlIjoidGVuYW50X2FkbWluIiwiaXNzIjoibmV4dXMtYWdlbnQiLCJhdWQiOiJuZXh1cy1hcGkiLCJpYXQiOjE3ODQ0MTU3OTcsImV4cCI6MTc4NzAwNzc5NywidHlwZSI6ImFjY2VzcyIsInRpZCI6IjAwMDAwMDAwLTAwMDAtMDAwMC0wMDAwLTAwMDAwMDAwMDAwMSJ9.YWUIUeTiM9elY-Yl-JS-SysIzxOEBTirO2xpGPvw9iU"

const DEMO_TENANT_ID = "00000000-0000-0000-0000-000000000001"

const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL || "/api",
  headers: {
    "Content-Type": "application/json",
    Authorization: `Bearer ${DEMO_TOKEN}`,
    "X-Tenant-ID": DEMO_TENANT_ID,
  },
})

api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      useAuthStore.getState().logout()
    }
    return Promise.reject(error)
  },
)

export default api
