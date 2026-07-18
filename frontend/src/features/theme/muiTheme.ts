import { createTheme, extendTheme, type ThemeOptions } from "@mui/material/styles"

const shared: ThemeOptions = {
  shape: { borderRadius: 8 },
  typography: { fontSize: 14 },
  components: {
    MuiButton: { styleOverrides: { root: { textTransform: "none" } } },
    MuiChip: { styleOverrides: { root: { fontWeight: 500 } } },
  },
}

const lightPalette = {
  primary: { main: "hsl(222.2 47.4% 11.2%)" },
  background: { default: "hsl(0 0% 100%)", paper: "hsl(0 0% 100%)" },
  text: { primary: "hsl(222.2 84% 4.9%)", secondary: "hsl(215.4 16.3% 46.9%)" },
  divider: "hsl(214.3 31.8% 91.4%)",
  error: { main: "hsl(0 84.2% 60.2%)" },
  warning: { main: "hsl(38 92% 50%)" },
  success: { main: "hsl(142 71% 45%)" },
}

const darkPalette = {
  primary: { main: "hsl(210 40% 98%)" },
  background: { default: "hsl(222.2 84% 4.9%)", paper: "hsl(217.2 32.6% 17.5%)" },
  text: { primary: "hsl(210 40% 98%)", secondary: "hsl(215 20.2% 65.1%)" },
  divider: "hsl(217.2 32.6% 17.5%)",
  error: { main: "hsl(0 62.8% 30.6%)" },
  warning: { main: "hsl(48 96% 53%)" },
  success: { main: "hsl(142 71% 45%)" },
}

export const lightTheme = createTheme({ ...shared, palette: { ...lightPalette, mode: "light" } })
export const darkTheme = createTheme({ ...shared, palette: { ...darkPalette, mode: "dark" } })

export const cssVarsTheme = extendTheme({
  colorSchemes: {
    light: { palette: lightPalette },
    dark: { palette: darkPalette },
  },
  ...shared,
})
