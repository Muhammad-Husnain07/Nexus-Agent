import { describe, it, expect, vi, beforeEach } from "vitest"
import axios from "axios"

vi.mock("@/features/auth/authStore", () => ({
  useAuthStore: { getState: () => ({ access_token: null, tenant_id: null }) },
}))

describe("api client infrastructure", () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it("creates axios instance with correct baseURL", async () => {
    const { api } = await import("@/lib/api")
    expect(api.defaults.baseURL).toBe("http://localhost:8000/api/v1")
    expect(api.defaults.headers["Content-Type"]).toBe("application/json")
  })

  it("exports injectAuth function", async () => {
    const { injectAuth } = await import("@/lib/api")
    expect(typeof injectAuth).toBe("function")
  })

  it("has request and response interceptors registered", async () => {
    const { api } = await import("@/lib/api")
    expect(api.interceptors.request.handlers.length).toBeGreaterThan(0)
    expect(api.interceptors.response.handlers.length).toBeGreaterThan(0)
  })
})
