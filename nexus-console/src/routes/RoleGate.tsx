import type { ReactNode } from "react"
import { useAuthStore } from "@/features/auth/authStore"

interface RoleGateProps {
  roles: string[]
  children: ReactNode
  fallback?: ReactNode
}

export default function RoleGate({ roles, children, fallback }: RoleGateProps) {
  const user = useAuthStore((s) => s.user)
  const role = user?.role
  if (!role || !roles.includes(role)) {
    return fallback || null
  }
  return <>{children}</>
}
