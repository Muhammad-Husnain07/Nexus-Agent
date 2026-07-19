import { useMemo, type ReactNode } from "react";
import {
  ThemeProvider as MuiThemeProvider,
  CssBaseline,
  useMediaQuery,
} from "@mui/material";
import { getTheme } from "./theme";
import { useThemeStore } from "../stores/theme-store";

export function ThemeProvider({ children }: { children: ReactNode }) {
  const mode = useThemeStore((s) => s.mode);
  const prefersDark = useMediaQuery("(prefers-color-scheme: dark)");
  const resolved = useMemo(
    () => (mode === "system" ? (prefersDark ? "dark" : "light") : mode),
    [mode, prefersDark]
  );
  const theme = useMemo(() => getTheme(resolved), [resolved]);

  return (
    <MuiThemeProvider theme={theme}>
      <CssBaseline />
      {children}
    </MuiThemeProvider>
  );
}
