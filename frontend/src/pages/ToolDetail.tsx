import { useParams } from "react-router-dom";
import { Box, Typography, Card, CardContent, Chip, Button, Grid } from "@mui/material";
import { useTool } from "../hooks/use-tools-api";
import { PageLoader } from "../components/UI/LoadingStates";

export default function ToolDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { data: tool, isLoading } = useTool(id!);

  if (isLoading) return <PageLoader />;
  if (!tool) return <Typography>Tool not found</Typography>;

  return (
    <Box>
      <Box display="flex" justifyContent="space-between" alignItems="center" mb={3}>
        <Typography variant="h4" fontWeight={700}>{tool.name}</Typography>
        <Box display="flex" gap={1}>
          <Button variant="outlined">Test</Button>
          <Button variant="contained">Edit</Button>
        </Box>
      </Box>

      <Grid container spacing={3}>
        <Grid item xs={12} md={8}>
          <Card>
            <CardContent>
              <Typography variant="h6" gutterBottom>Description</Typography>
              <Typography variant="body1" color="text.secondary">{tool.description}</Typography>
            </CardContent>
          </Card>
        </Grid>
        <Grid item xs={12} md={4}>
          <Card>
            <CardContent>
              <Typography variant="subtitle2" color="text.secondary" gutterBottom>Details</Typography>
              <Box mb={1}>
                <Typography variant="caption" color="text.secondary">Category</Typography>
                <Chip label={tool.category} size="small" sx={{ ml: 1 }} />
              </Box>
              <Box mb={1}>
                <Typography variant="caption" color="text.secondary">Risk Level</Typography>
                <Chip label={tool.risk_level} size="small" color={tool.risk_level === "low" ? "success" : "warning"} sx={{ ml: 1 }} />
              </Box>
              <Box mb={1}>
                <Typography variant="caption" color="text.secondary">Endpoint</Typography>
                <Typography variant="body2">{tool.endpoint_url}</Typography>
              </Box>
              <Box mb={1}>
                <Typography variant="caption" color="text.secondary">Method</Typography>
                <Chip label={tool.http_method} size="small" color="primary" sx={{ ml: 1 }} />
              </Box>
              <Box>
                <Typography variant="caption" color="text.secondary">Version</Typography>
                <Typography variant="body2">v{tool.version}</Typography>
              </Box>
            </CardContent>
          </Card>
        </Grid>
      </Grid>
    </Box>
  );
}
