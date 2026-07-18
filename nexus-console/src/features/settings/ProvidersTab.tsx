import Box from "@mui/material/Box"
import Card from "@mui/material/Card"
import CardContent from "@mui/material/CardContent"
import Typography from "@mui/material/Typography"
import InfoIcon from "@mui/icons-material/Info"

export default function ProvidersTab() {
  return (
    <Box sx={{ maxWidth: 480 }}>
      <Card variant="outlined">
        <CardContent>
          <Box sx={{ display: "flex", gap: 2 }}>
            <InfoIcon color="info" sx={{ flexShrink: 0, mt: 0.5 }} />
            <div>
              <Typography variant="subtitle2" sx={{ fontWeight: 600, mb: 0.5 }}>Configured via Environment Variables</Typography>
              <Typography variant="body2" color="text.secondary">
                LLM providers are configured at startup through environment variables (e.g.{" "}
                <Typography component="span" variant="caption" sx={{ bgcolor: "grey.100", px: 0.5, borderRadius: 0.5, fontFamily: "monospace" }}>NEXUS_LLM__PROVIDERS</Typography>
                ). Changes require a server restart to take effect.
              </Typography>
              <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
                Runtime provider management is coming in a future release.
              </Typography>
            </div>
          </Box>
        </CardContent>
      </Card>
    </Box>
  )
}
