import MUISkeleton from "@mui/material/Skeleton"

interface SkeletonProps {
  className?: string
  sx?: Record<string, unknown>
  width?: string | number
  height?: string | number
}

export default function Skeleton({ sx, width, height }: SkeletonProps) {
  return (
    <MUISkeleton
      sx={{ ...sx }}
      width={width}
      height={height}
      animation="pulse"
      variant="rounded"
    />
  )
}
