import { extendTheme } from "@mui/material/styles"

export const theme = extendTheme({
  colorSchemes: {
    light: {
      palette: {
        primary: { main: "hsl(222.2 47.4% 11.2%)", contrastText: "#fff" },
        secondary: { main: "hsl(215.4 16.3% 46.9%)" },
        error: { main: "hsl(0 84.2% 60.2%)" },
        warning: { main: "hsl(38 92% 50%)" },
        success: { main: "hsl(142 71% 45%)" },
        info: { main: "hsl(200 98% 39%)" },
        background: { default: "hsl(0 0% 100%)", paper: "hsl(0 0% 100%)" },
        text: { primary: "hsl(222.2 84% 4.9%)", secondary: "hsl(215.4 16.3% 46.9%)", disabled: "hsl(215.4 16.3% 46.9% / 0.5)" },
        divider: "hsl(214.3 31.8% 91.4%)",
      },
    },
    dark: {
      palette: {
        primary: { main: "hsl(210 40% 98%)", contrastText: "hsl(222.2 84% 4.9%)" },
        secondary: { main: "hsl(215 20.2% 65.1%)" },
        error: { main: "hsl(0 62.8% 30.6%)" },
        warning: { main: "hsl(48 96% 53%)" },
        success: { main: "hsl(142 71% 45%)" },
        info: { main: "hsl(200 98% 39%)" },
        background: { default: "hsl(222.2 84% 4.9%)", paper: "hsl(217.2 32.6% 17.5%)" },
        text: { primary: "hsl(210 40% 98%)", secondary: "hsl(215 20.2% 65.1%)", disabled: "hsl(215 20.2% 65.1% / 0.5)" },
        divider: "hsl(217.2 32.6% 17.5%)",
      },
    },
  },
  shape: { borderRadius: 8 },
  typography: {
    fontSize: 14,
    h1: { fontSize: "2.25rem", fontWeight: 700, lineHeight: 1.2 },
    h2: { fontSize: "1.875rem", fontWeight: 700, lineHeight: 1.3 },
    h3: { fontSize: "1.5rem", fontWeight: 600, lineHeight: 1.35 },
    h4: { fontSize: "1.25rem", fontWeight: 600, lineHeight: 1.4 },
    h5: { fontSize: "1.125rem", fontWeight: 600, lineHeight: 1.45 },
    h6: { fontSize: "1rem", fontWeight: 600, lineHeight: 1.5 },
    body1: { fontSize: "1rem", lineHeight: 1.5 },
    body2: { fontSize: "0.875rem", lineHeight: 1.5 },
    caption: { fontSize: "0.75rem", lineHeight: 1.4 },
    overline: { fontSize: "0.75rem", fontWeight: 500, textTransform: "uppercase", letterSpacing: "0.08em" },
    button: { textTransform: "none", fontWeight: 500 },
  },
  components: {
    MuiButton: {
      defaultProps: { disableElevation: true },
      styleOverrides: { root: { textTransform: "none", fontWeight: 500, borderRadius: 8 } },
    },
    MuiCard: {
      styleOverrides: { root: { backgroundImage: "none" } },
    },
    MuiChip: {
      styleOverrides: { root: { fontWeight: 500 } },
    },
  },
})
