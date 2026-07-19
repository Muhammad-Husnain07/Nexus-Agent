import { Box, Typography, Card, CardContent, TextField, Button, Select, MenuItem, FormControl, InputLabel, Tabs, Tab, } from "@mui/material";
import PlayArrowIcon from "@mui/icons-material/PlayArrow";
import ContentCopyIcon from "@mui/icons-material/ContentCopy";
import SaveIcon from "@mui/icons-material/Save";
import { useState } from "react";

export default function TestPlaygroundPage() {
  const [tab, setTab] = useState(0);
  const [url, setUrl] = useState("");
  const [method, setMethod] = useState("GET");

  return (
    <Box>
      <Typography variant="h4" fontWeight={700} mb={3}>Test Playground</Typography>
      <Card>
        <CardContent>
          <Box display="flex" gap={2} mb={2}>
            <FormControl size="small" sx={{ minWidth: 100 }}>
              <InputLabel>Method</InputLabel>
              <Select value={method} label="Method" onChange={(e) => setMethod(e.target.value)}>
                <MenuItem value="GET">GET</MenuItem>
                <MenuItem value="POST">POST</MenuItem>
                <MenuItem value="PUT">PUT</MenuItem>
                <MenuItem value="DELETE">DELETE</MenuItem>
              </Select>
            </FormControl>
            <TextField fullWidth size="small" label="Endpoint URL" value={url} onChange={(e) => setUrl(e.target.value)} />
            <Button variant="contained" startIcon={<PlayArrowIcon />}>Send</Button>
          </Box>
          <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ mb: 2 }}>
            <Tab label="Body" />
            <Tab label="Headers" />
            <Tab label="Response" />
          </Tabs>
          {tab === 2 && (
            <Box
              sx={{ bgcolor: "grey.100", p: 2, borderRadius: 1, minHeight: 200, fontFamily: "monospace", fontSize: 14 }}
            >
              <Typography color="text.secondary">Response will appear here</Typography>
            </Box>
          )}
        </CardContent>
      </Card>
    </Box>
  );
}
