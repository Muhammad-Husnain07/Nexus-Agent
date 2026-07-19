import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Box, Button, Typography, Chip, Switch, IconButton } from "@mui/material";
import AddIcon from "@mui/icons-material/Add";
import EditIcon from "@mui/icons-material/Edit";
import DeleteIcon from "@mui/icons-material/Delete";
import type { GridColDef } from "@mui/x-data-grid";
import { DataTable } from "../components/UI/DataTable";
import { useToolsList } from "../hooks/use-tools-api";
import FilterPanel from "../components/UI/FilterPanel";

export default function ToolsListPage() {
  const navigate = useNavigate();
  const [page, setPage] = useState(0);
  const [search, setSearch] = useState("");
  const { data, isLoading } = useToolsList({ page: page + 1 });

  const columns: GridColDef[] = [
    { field: "name", headerName: "Name", flex: 1, minWidth: 150 },
    { field: "category", headerName: "Category", width: 120,
      renderCell: (p) => <Chip label={p.value} size="small" variant="outlined" /> },
    { field: "risk_level", headerName: "Risk", width: 100,
      renderCell: (p) => (
        <Chip label={p.value} size="small"
          color={p.value === "low" ? "success" : p.value === "medium" ? "warning" : "error"}
        />
      )},
    { field: "enabled", headerName: "Enabled", width: 100,
      renderCell: (p) => <Switch checked={!!p.value} size="small" /> },
    { field: "requires_approval", headerName: "Requires Approval", width: 140 },
    {
      field: "actions", headerName: "Actions", width: 120, sortable: false,
      renderCell: (p) => (
        <Box>
          <IconButton size="small" onClick={() => navigate(`/tools/${p.id}`)}>
            <EditIcon fontSize="small" />
          </IconButton>
          <IconButton size="small" color="error">
            <DeleteIcon fontSize="small" />
          </IconButton>
        </Box>
      ),
    },
  ];

  return (
    <Box>
      <Box display="flex" justifyContent="space-between" alignItems="center" mb={3}>
        <Typography variant="h4" fontWeight={700}>Tools</Typography>
        <Button variant="contained" startIcon={<AddIcon />} onClick={() => navigate("/tools/new")}>
          Create Tool
        </Button>
      </Box>

      <FilterPanel
        filters={[
          { key: "search", label: "Search", type: "text", value: search, onChange: setSearch },
        ]}
        onClear={() => setSearch("")}
      />

      <DataTable
        rows={(data?.items || []) as any}
        columns={columns}
        loading={isLoading}
        total={data?.total}
        page={page}
        onPageChange={setPage}
      />
    </Box>
  );
}
