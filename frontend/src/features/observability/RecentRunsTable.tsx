import Box from "@mui/material/Box"
import Typography from "@mui/material/Typography"
import Table from "@mui/material/Table"
import TableHead from "@mui/material/TableHead"
import TableBody from "@mui/material/TableBody"
import TableRow from "@mui/material/TableRow"
import TableCell from "@mui/material/TableCell"
import TableContainer from "@mui/material/TableContainer"
import Paper from "@mui/material/Paper"
import Chip from "@mui/material/Chip"
import Alert from "@mui/material/Alert"
import { ExternalLink } from "lucide-react"
import TableSkeleton from "@/components/skeletons/TableSkeleton"
import { useGetRecentRuns } from "@/lib/api/metrics"
import type { RecentRun } from "@/lib/types"

const statusColors: Record<string, "success" | "error" | "warning" | "info" | "default"> = {
  completed: "success", failed: "error", interrupted: "warning", running: "info", cancelled: "default",
}

function formatDuration(run: RecentRun): string {
  if (!run.ended_at) return run.status === "running" ? "running..." : "\u2014"
  const ms = new Date(run.ended_at).getTime() - new Date(run.started_at).getTime()
  const secs = Math.floor(ms / 1000)
  if (secs < 60) return `${secs}s`
  const mins = Math.floor(secs / 60)
  return `${mins}m ${secs % 60}s`
}

export default function RecentRunsTable() {
  const { data, isLoading, isError, error } = useGetRecentRuns(20)

  return (
    <div>
      <Typography variant="subtitle1" sx={{ fontWeight: 600, mb: 1.5 }}>Recent Runs</Typography>

      {isLoading ? (
        <TableSkeleton rows={5} columns={6} />
      ) : isError ? (
        <Alert severity="error">{(error as Error)?.message || "Failed to load recent runs"}</Alert>
      ) : !data || data.length === 0 ? (
        <Box sx={{ textAlign: "center", py: 6, color: "text.secondary" }}>
          <Typography variant="body2">No recent AgentRuns found.</Typography>
          <Typography variant="caption" sx={{ opacity: 0.6, display: "block", mt: 0.5 }}>Agent run history \u2014 backend endpoint pending.</Typography>
        </Box>
      ) : (
        <TableContainer component={Paper} variant="outlined">
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell sx={{ fontWeight: 600 }}>Session</TableCell>
                <TableCell sx={{ fontWeight: 600 }}>Status</TableCell>
                <TableCell sx={{ fontWeight: 600 }} align="right">Tokens</TableCell>
                <TableCell sx={{ fontWeight: 600 }} align="right">Cost</TableCell>
                <TableCell sx={{ fontWeight: 600 }} align="right">Duration</TableCell>
                <TableCell sx={{ fontWeight: 600 }} align="center">Trace</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {data.map((run) => (
                <TableRow key={run.id} hover>
                  <TableCell><Typography variant="caption" sx={{ fontFamily: "monospace" }}>{run.session_id.slice(0, 8)}...</Typography></TableCell>
                  <TableCell><Chip label={run.status} size="small" color={statusColors[run.status] ?? "default"} variant="outlined" /></TableCell>
                  <TableCell align="right">{run.total_tokens.toLocaleString()}</TableCell>
                  <TableCell align="right">${run.total_cost_usd.toFixed(2)}</TableCell>
                  <TableCell align="right">{formatDuration(run)}</TableCell>
                  <TableCell align="center">
                    {run.langsmith_url ? (
                      <a href={run.langsmith_url} target="_blank" rel="noopener noreferrer" style={{ color: "inherit", textDecoration: "none", opacity: 0.6 }}>
                        <ExternalLink size={14} />
                      </a>
                    ) : (
                      <Typography variant="caption" sx={{ opacity: 0.3 }}>\u2014</Typography>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      )}
    </div>
  )
}
