import { Box, Typography, Button, TextField, Select, MenuItem, FormControl, InputLabel, IconButton, } from "@mui/material";
import AddIcon from "@mui/icons-material/Add";
import DeleteIcon from "@mui/icons-material/Delete";
import ContentCopyIcon from "@mui/icons-material/ContentCopy";
import { useState } from "react";

interface Field {
  name: string;
  type: string;
  required: boolean;
}

export default function JsonSchemaEditor() {
  const [fields, setFields] = useState<Field[]>([]);

  const addField = () => setFields([...fields, { name: "", type: "string", required: false }]);
  const removeField = (i: number) => setFields(fields.filter((_, idx) => idx !== i));

  return (
    <Box>
      <Box display="flex" justifyContent="space-between" alignItems="center" mb={2}>
        <Typography variant="subtitle2">Schema Fields</Typography>
        <Button size="small" startIcon={<AddIcon />} onClick={addField}>Add Field</Button>
      </Box>
      {fields.map((f, i) => (
        <Box key={i} display="flex" gap={1} alignItems="center" mb={1}>
          <TextField size="small" label="Name" value={f.name} sx={{ flex: 1 }} />
          <FormControl size="small" sx={{ minWidth: 120 }}>
            <InputLabel>Type</InputLabel>
            <Select value={f.type} label="Type">
              <MenuItem value="string">String</MenuItem>
              <MenuItem value="number">Number</MenuItem>
              <MenuItem value="boolean">Boolean</MenuItem>
              <MenuItem value="object">Object</MenuItem>
              <MenuItem value="array">Array</MenuItem>
            </Select>
          </FormControl>
          <IconButton size="small" color="error" onClick={() => removeField(i)}>
            <DeleteIcon />
          </IconButton>
        </Box>
      ))}
      {fields.length === 0 && (
        <Typography variant="body2" color="text.secondary">No fields defined. Click "Add Field" to start.</Typography>
      )}
    </Box>
  );
}
