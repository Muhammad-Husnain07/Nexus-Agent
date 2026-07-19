import { useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Box,
  Grid,
  Card,
  CardContent,
  CardHeader,
  Typography,
  Button,
  List,
  ListItem,
  ListItemText,
  ListItemIcon,
  Chip,
  Skeleton,
} from "@mui/material";
import ChatIcon from "@mui/icons-material/Chat";
import BuildIcon from "@mui/icons-material/Build";
import CheckCircleIcon from "@mui/icons-material/CheckCircle";
import AttachMoneyIcon from "@mui/icons-material/AttachMoney";
import TrendingUpIcon from "@mui/icons-material/TrendingUp";


const stats = [
  { label: "Total Sessions", value: "12", icon: <ChatIcon />, trend: "+3", color: "primary" as const },
  { label: "Tools Registered", value: "18", icon: <BuildIcon />, trend: "+2", color: "success" as const },
  { label: "Pending Approvals", value: "3", icon: <CheckCircleIcon />, trend: "", color: "warning" as const },
  { label: "Cost This Month", value: "$0.42", icon: <AttachMoneyIcon />, trend: "-12%", color: "info" as const },
];

const quickActions = [
  { label: "New Chat", icon: <ChatIcon />, path: "/chat" },
  { label: "Register Tool", icon: <BuildIcon />, path: "/tools/new" },
  { label: "View Approvals", icon: <CheckCircleIcon />, path: "/approvals" },
];

export default function DashboardPage() {
  const navigate = useNavigate();
  const [loading] = useState(false);

  return (
    <Box>
      <Typography variant="h4" fontWeight={700} gutterBottom>
        Welcome 👋
      </Typography>

      <Grid container spacing={3} sx={{ mb: 4 }}>
        {stats.map((s) => (
          <Grid item xs={12} sm={6} md={3} key={s.label}>
            <Card sx={{ cursor: "default" }}>
              <CardContent>
                <Box display="flex" justifyContent="space-between" alignItems="flex-start">
                  <Box>
                    <Typography variant="body2" color="text.secondary">
                      {s.label}
                    </Typography>
                    {loading ? (
                      <Skeleton width={60} />
                    ) : (
                      <Typography variant="h4" fontWeight={700}>
                        {s.value}
                      </Typography>
                    )}
                  </Box>
                  <Box
                    sx={{
                      p: 1,
                      borderRadius: 2,
                      bgcolor: (t) =>
                        t.palette.mode === "dark" ? "rgba(255,255,255,0.05)" : `${s.color}.light`,
                      color: `${s.color}.main`,
                      display: "flex",
                    }}
                  >
                    {s.icon}
                  </Box>
                </Box>
                {s.trend && (
                  <Box display="flex" alignItems="center" gap={0.5} mt={1}>
                    <TrendingUpIcon
                      fontSize="small"
                      color={s.trend.startsWith("+") ? "success" : "error"}
                    />
                    <Typography variant="caption" color={s.trend.startsWith("+") ? "success.main" : "error.main"}>
                      {s.trend} from last month
                    </Typography>
                  </Box>
                )}
              </CardContent>
            </Card>
          </Grid>
        ))}
      </Grid>

      <Grid container spacing={3}>
        <Grid item xs={12} md={8}>
          <Card>
            <CardHeader title="Quick Actions" />
            <CardContent>
              <Grid container spacing={2}>
                {quickActions.map((action) => (
                  <Grid item xs={12} sm={4} key={action.label}>
                    <Button
                      variant="outlined"
                      fullWidth
                      sx={{ py: 3, flexDirection: "column", gap: 1 }}
                      onClick={() => navigate(action.path)}
                    >
                      {action.icon}
                      <Typography variant="body2">{action.label}</Typography>
                    </Button>
                  </Grid>
                ))}
              </Grid>
            </CardContent>
          </Card>
        </Grid>

        <Grid item xs={12} md={4}>
          <Card>
            <CardHeader title="Recent Activity" />
            <CardContent sx={{ p: 0 }}>
              <List dense>
                {["Chat session created", "Tool 'get_weather' tested", "Approval pending"].map(
                  (item, i) => (
                    <ListItem key={i} divider>
                      <ListItemIcon sx={{ minWidth: 36 }}>
                        <Chip label={i + 1} size="small" color="primary" variant="outlined" />
                      </ListItemIcon>
                      <ListItemText primary={item} />
                    </ListItem>
                  )
                )}
              </List>
            </CardContent>
          </Card>
        </Grid>
      </Grid>
    </Box>
  );
}
