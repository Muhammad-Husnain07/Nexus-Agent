import Box from "@mui/material/Box"
import Typography from "@mui/material/Typography"
import Button from "@mui/material/Button"
import type { ReactNode } from "react"

interface EmptyStateProps {
  icon?: ReactNode
  title: string
  description?: string
  action?: { label: string; onClick: () => void }
}

export default function EmptyState({ icon, title, description, action }: EmptyStateProps) {
  return (
    <Box sx={{ textAlign: "center", py: 8, color: "text.secondary" }}>
      {icon && <Box sx={{ mb: 1, opacity: 0.5 }}>{icon}</Box>}
      <Typography variant="h6" sx={{ fontWeight: 600, mb: 0.5 }}>{title}</Typography>
      {description && <Typography variant="body2" sx={{ mb: 2 }}>{description}</Typography>}
      {action && <Button variant="outlined" onClick={action.onClick}>{action.label}</Button>}
    </Box>
  )
}
