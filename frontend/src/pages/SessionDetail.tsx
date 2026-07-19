import { useParams } from "react-router-dom";
import { Box, Typography } from "@mui/material";

export default function SessionDetailPage() {
  const { id } = useParams();
  return (
    <Box>
      <Typography variant="h4" fontWeight={700}>Session: {id?.slice(0, 8)}</Typography>
    </Box>
  );
}
