import { useEffect, type ReactNode } from "react"
import { CssVarsProvider } from "@mui/material/styles"
import CssBaseline from "@mui/material/CssBaseline"
import { SnackbarProvider } from "notistack"
import { theme } from "./theme"
import { useThemeStore } from "./themeStore"

export { useThemeStore } from "./themeStore"

const MODE_SCRIPT = `(function(){try{var m=JSON.parse(localStorage.getItem('nexus-theme')||'{}');var mode=m.state&&m.state.mode||'light';document.documentElement.setAttribute('data-color-scheme',mode)}catch(e){}})()`

export default function ThemeProvider({ children }: { children: ReactNode }) {
  const mode = useThemeStore((s) => s.mode)

  useEffect(() => {
    document.documentElement.setAttribute("data-color-scheme", mode)
  }, [mode])

  return (
    <>
      <script dangerouslySetInnerHTML={{ __html: MODE_SCRIPT }} />
      <CssVarsProvider theme={theme} defaultMode={mode}>
        <CssBaseline />
        <SnackbarProvider
          maxSnack={3}
          anchorOrigin={{ vertical: "bottom", horizontal: "right" }}
          autoHideDuration={4000}
          dense
          preventDuplicate
        >
          {children}
        </SnackbarProvider>
      </CssVarsProvider>
    </>
  )
}
