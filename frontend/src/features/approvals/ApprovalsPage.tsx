import Typography from "@mui/material/Typography"
import ApprovalsList from "./ApprovalsList"

export default function ApprovalsPage() {
  return (
    <div>
      <Typography variant="h5" sx={{ fontWeight: 700, mb: 2 }}>Approvals</Typography>
      <ApprovalsList />
    </div>
  )
}
