import { DataGrid, type GridColDef } from "@mui/x-data-grid";
import { Chip, Switch, IconButton, Box } from "@mui/material";
import EditIcon from "@mui/icons-material/Edit";
import type { ToolDefinition } from "../../types/tool";

const columns: GridColDef[] = [
  { field: "name", headerName: "Name", flex: 1 },
  { field: "category", headerName: "Category", width: 120, renderCell: (p) => <Chip label={p.value} size="small" variant="outlined" /> },
  { field: "risk_level", headerName: "Risk", width: 100, renderCell: (p) => <Chip label={p.value} size="small" color={p.value === "low" ? "success" : "warning"} /> },
  { field: "enabled", headerName: "Enabled", width: 100, renderCell: (p) => <Switch checked={!!p.value} size="small" /> },
  { field: "actions", headerName: "", width: 80, sortable: false, renderCell: () => <IconButton size="small"><EditIcon fontSize="small" /></IconButton> },
];

interface Props { rows: ToolDefinition[]; loading?: boolean; }

export default function ToolsTable({ rows, loading }: Props) {
  return <DataGrid rows={rows} columns={columns} loading={loading} autoHeight disableRowSelectionOnClick pageSizeOptions={[20, 50, 100]} />;
}
