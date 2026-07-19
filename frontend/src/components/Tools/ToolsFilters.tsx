import { Box, TextField, Select, MenuItem, FormControl, InputLabel, Switch, FormControlLabel, Autocomplete, Button } from "@mui/material";
import ClearIcon from "@mui/icons-material/Clear";
import { useState } from "react";

const categories = ["data", "entertainment", "dev", "education"];
const riskLevels = ["low", "medium", "high", "critical"];

export default function ToolsFilters() {
  const [search, setSearch] = useState(""); const [category, setCategory] = useState(""); const [risk, setRisk] = useState("");
  return (
    <Box display="flex" gap={2} flexWrap="wrap" alignItems="center" mb={2}>
      <TextField size="small" label="Search" value={search} onChange={(e) => setSearch(e.target.value)} sx={{ minWidth: 200 }} />
      <FormControl size="small" sx={{ minWidth: 150 }}><InputLabel>Category</InputLabel><Select value={category} label="Category" onChange={(e) => setCategory(e.target.value)}>
        <MenuItem value="">All</MenuItem>{categories.map((c) => <MenuItem key={c} value={c}>{c}</MenuItem>)}</Select></FormControl>
      <FormControl size="small" sx={{ minWidth: 120 }}><InputLabel>Risk Level</InputLabel><Select value={risk} label="Risk Level" onChange={(e) => setRisk(e.target.value)}>
        <MenuItem value="">All</MenuItem>{riskLevels.map((r) => <MenuItem key={r} value={r}>{r}</MenuItem>)}</Select></FormControl>
      <Button size="small" startIcon={<ClearIcon />} onClick={() => { setSearch(""); setCategory(""); setRisk(""); }}>Clear</Button>
    </Box>
  );
}
