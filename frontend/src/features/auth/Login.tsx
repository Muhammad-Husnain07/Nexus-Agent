import { useForm } from "react-hook-form"
import { z } from "zod"
import { zodResolver } from "@hookform/resolvers/zod"
import { useNavigate, useSearchParams } from "react-router-dom"
import Box from "@mui/material/Box"
import Typography from "@mui/material/Typography"
import TextField from "@mui/material/TextField"
import Button from "@mui/material/Button"
import { toast } from "sonner"
import { api } from "@/lib/api"
import { useAuthStore, decodeUserFromToken } from "./authStore"
import type { LoginResponse } from "@/lib/types"

const loginSchema = z.object({
  email: z.string().email("Enter a valid email address"),
})

type LoginForm = z.infer<typeof loginSchema>

export default function Login() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const login = useAuthStore((s) => s.login)

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<LoginForm>({
    resolver: zodResolver(loginSchema),
  })

  const onSubmit = async (data: LoginForm) => {
    try {
      const res = await api.post<LoginResponse>("/auth/login", { email: data.email })
      const user = decodeUserFromToken(res.data.access_token, data.email)
      if (!user) {
        toast.error("Failed to decode authentication token")
        return
      }
      login(res.data.access_token, res.data.refresh_token, user)
      const redirect = searchParams.get("redirect") || "/"
      navigate(redirect, { replace: true })
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Login failed")
    }
  }

  return (
    <Box sx={{ display: "flex", minHeight: "100vh", alignItems: "center", justifyContent: "center" }}>
      <Box sx={{ width: "100%", maxWidth: 400, display: "flex", flexDirection: "column", gap: 3 }}>
        <Box sx={{ textAlign: "center" }}>
          <Typography variant="h4" sx={{ fontWeight: 700 }}>
            Nexus Agent
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
            Sign in to your account
          </Typography>
        </Box>
        <form onSubmit={handleSubmit(onSubmit)}>
          <Box sx={{ display: "flex", flexDirection: "column", gap: 2 }}>
            <TextField
              id="email"
              label="Email"
              type="email"
              placeholder="you@example.com"
              {...register("email")}
              error={!!errors.email}
              helperText={errors.email?.message}
              size="small"
              fullWidth
            />
            <Button type="submit" variant="contained" size="large" disabled={isSubmitting} fullWidth>
              {isSubmitting ? "Signing in..." : "Sign in"}
            </Button>
          </Box>
        </form>
      </Box>
    </Box>
  )
}
