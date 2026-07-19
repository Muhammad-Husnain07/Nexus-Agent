import { Box, TextField, Select, MenuItem, FormControl, InputLabel, Button, Chip } from "@mui/material";
import PlayArrowIcon from "@mui/icons-material/PlayArrow";
import { useState } from "react";

export default function RequestBuilder() {
  const [url, setUrl] = useState(""); const [method, setMethod] = useState("GET");
  return (
    <Box display="flex" gap={2} alignItems="center" flexWrap="wrap">
      <FormControl size="small" sx={{ minWidth: 100 }}><InputLabel>Method</InputLabel><Select value={method} label="Method" onChange={(e) => setMethod(e.target.value)}>
        <MenuItem value="GET">GET</MenuItem><MenuItem value="POST">POST</MenuItem><MenuItem value="PUT">PUT</MenuItem><MenuItem value="DELETE">DELETE</MenuItem></Select></FormControl>
      <TextField fullWidth size="small" label="URL" value={url} onChange={(e) => setUrl(e.target.value)} sx={{ flex: 1, minWidth: 200 }} />
      <Button variant="contained" startIcon={<PlayArrowIcon />}>Send</Button>
    </Box>
  );
}
