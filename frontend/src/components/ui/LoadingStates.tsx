import { Box, CircularProgress, Skeleton } from "@mui/material";

export function PageLoader() {
  return (
    <Box display="flex" justifyContent="center" alignItems="center" minHeight="60vh">
      <CircularProgress />
    </Box>
  );
}

export function CardLoader() {
  return <Skeleton variant="rectangular" height={200} sx={{ borderRadius: 2 }} />;
}

export function TableLoader({ rows = 5 }: { rows?: number }) {
  return (
    <Box>
      {Array.from({ length: rows }).map((_, i) => (
        <Skeleton key={i} height={52} sx={{ mb: 1 }} />
      ))}
    </Box>
  );
}

export function ChartLoader({ height = 300 }: { height?: number }) {
  return <Skeleton variant="rectangular" height={height} sx={{ borderRadius: 2 }} />;
}
