import type { ReactNode } from "react"
import { ThemeProvider } from "@mui/material/styles"
import { useThemeStore } from "./themeStore"
import { lightTheme, darkTheme } from "./muiTheme"

export default function ThemeWrapper({ children }: { children: ReactNode }) {
  const mode = useThemeStore((s) => s.mode)
  const theme = mode === "dark" ? darkTheme : lightTheme

  return <ThemeProvider theme={theme}>{children}</ThemeProvider>
}
