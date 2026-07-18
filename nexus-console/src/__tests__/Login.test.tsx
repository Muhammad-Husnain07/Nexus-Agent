import { describe, it, expect, vi, beforeEach } from "vitest"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { BrowserRouter } from "react-router-dom"
import Login from "@/features/auth/Login"

vi.mock("@/lib/api", () => ({
  api: {
    post: vi.fn(),
    interceptors: {
      request: { use: vi.fn(), clear: vi.fn() },
      response: { use: vi.fn(), clear: vi.fn() },
    },
    defaults: { baseURL: "" },
  },
}))

vi.mock("sonner", () => ({
  toast: { error: vi.fn() },
}))

vi.mock("@/features/auth/authStore", () => ({
  useAuthStore: vi.fn((sel) => sel?.({ login: vi.fn(), user: null, tenant_id: null })),
  decodeUserFromToken: vi.fn(() => ({ id: "1", email: "test@test.com", role: "end_user", tenant_id: null })),
}))

const renderLogin = () =>
  render(
    <BrowserRouter>
      <Login />
    </BrowserRouter>,
  )

describe("Login page", () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it("renders the login form", () => {
    renderLogin()
    expect(screen.getByText("Sign in to your account")).toBeInTheDocument()
    expect(screen.getByPlaceholderText("you@example.com")).toBeInTheDocument()
  })

  it("shows validation error for empty email", async () => {
    renderLogin()
    const user = userEvent.setup()
    const button = screen.getByRole("button", { name: /sign in/i })

    await user.click(button)

    expect(await screen.findByText("Enter a valid email address")).toBeInTheDocument()
  })
})
