import { useTheme, useMediaQuery as useMuiMediaQuery } from "@mui/material";

export function useMediaQuery(query: string) {
  return useMuiMediaQuery(query);
}

export function useIsMobile() {
  const theme = useTheme();
  return useMediaQuery(theme.breakpoints.down("md"));
}

export function useIsDesktop() {
  const theme = useTheme();
  return useMediaQuery(theme.breakpoints.up("md"));
}
