import Card from "@mui/material/Card"
import CardContent from "@mui/material/CardContent"
import Box from "@mui/material/Box"
import Skeleton from "./Skeleton"

interface CardSkeletonProps {
  count?: number
}

export default function CardSkeleton({ count = 6 }: CardSkeletonProps) {
  return (
    <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", sm: "1fr 1fr", lg: "1fr 1fr 1fr" }, gap: 2 }}>
      {Array.from({ length: count }).map((_, i) => (
        <Card key={i} variant="outlined">
          <CardContent sx={{ "&:last-child": { pb: 2 } }}>
            <Box sx={{ display: "flex", flexDirection: "column", gap: 1.5 }}>
              <Skeleton height={20} width="75%" />
              <Skeleton height={12} width="50%" />
              <Box sx={{ display: "flex", justifyContent: "space-between" }}>
                <Skeleton width={64} height={12} />
                <Skeleton width={48} height={12} />
              </Box>
            </Box>
          </CardContent>
        </Card>
      ))}
    </Box>
  )
}
