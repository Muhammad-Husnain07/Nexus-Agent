import { Box, Skeleton, Typography } from "@mui/material";
import { DataGrid, type GridColDef, type GridRowsProp } from "@mui/x-data-grid";

interface Props<T> {
  rows: T[];
  columns: GridColDef[];
  loading?: boolean;
  total?: number;
  page?: number;
  pageSize?: number;
  onPageChange?: (page: number) => void;
  onPageSizeChange?: (size: number) => void;
  checkboxSelection?: boolean;
  getRowId?: (row: T) => string;
  emptyMessage?: string;
  toolbar?: React.ReactNode;
}

export function DataTable<T extends Record<string, unknown>>({
  rows, columns, loading, total, page = 0, pageSize = 20,
  onPageChange, onPageSizeChange, checkboxSelection, getRowId,
  emptyMessage = "No data found", toolbar,
}: Props<T>) {
  if (loading) {
    return (
      <Box sx={{ p: 2 }}>
        {Array.from({ length: 5 }).map((_, i) => (
          <Skeleton key={i} height={52} sx={{ mb: 1 }} />
        ))}
      </Box>
    );
  }
  return (
    <Box sx={{ width: "100%" }}>
      {toolbar && <Box sx={{ mb: 2 }}>{toolbar}</Box>}
      <DataGrid
        rows={rows as GridRowsProp}
        columns={columns}
        rowCount={total || rows.length}
        paginationMode="server"
        paginationModel={{ page, pageSize }}
        onPaginationModelChange={(m) => {
          onPageChange?.(m.page);
          onPageSizeChange?.(m.pageSize);
        }}
        pageSizeOptions={[20, 50, 100]}
        checkboxSelection={checkboxSelection}
        getRowId={getRowId || ((r: any) => r.id)}
        autoHeight
        disableRowSelectionOnClick
        sx={{
          "& .MuiDataGrid-cell": { py: 1 },
          "& .MuiDataGrid-columnHeaders": { bgcolor: "action.hover", borderRadius: 1 },
        }}
        slots={{
          noRowsOverlay: () => (
            <Box display="flex" alignItems="center" justifyContent="center" height="100%">
              <Typography color="text.secondary">{emptyMessage}</Typography>
            </Box>
          ),
        }}
      />
    </Box>
  );
}
