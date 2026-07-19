import { Box, TextField, Select, MenuItem, FormControl, InputLabel, Button } from "@mui/material";
import ClearIcon from "@mui/icons-material/Clear";

interface Filter {
  key: string; label: string; type: "text" | "select" | "boolean";
  value: unknown; onChange: (value: unknown) => void;
  options?: { label: string; value: unknown }[];
}

interface Props { filters: Filter[]; onClear: () => void; }

export default function FilterPanel({ filters, onClear }: Props) {
  const activeCount = filters.filter((f) => f.value !== "" && f.value !== undefined && f.value !== null).length;
  return (
    <Box sx={{ display: "flex", gap: 2, flexWrap: "wrap", alignItems: "center", mb: 2 }}>
      {filters.map((f) => (
        <Box key={f.key} sx={{ minWidth: 160 }}>
          {f.type === "text" && (
            <TextField size="small" label={f.label} value={(f.value as string) || ""} onChange={(e) => f.onChange(e.target.value)} fullWidth />
          )}
          {f.type === "select" && (
            <FormControl size="small" fullWidth>
              <InputLabel>{f.label}</InputLabel>
              <Select value={f.value || ""} label={f.label} onChange={(e) => f.onChange(e.target.value)}>
                <MenuItem value="">All</MenuItem>
                {f.options?.map((o) => (
                  <MenuItem key={String(o.value)} value={o.value as string}>{o.label}</MenuItem>
                ))}
              </Select>
            </FormControl>
          )}
        </Box>
      ))}
      {activeCount > 0 && (
        <Button size="small" startIcon={<ClearIcon />} onClick={onClear}>Clear ({activeCount})</Button>
      )}
    </Box>
  );
}
