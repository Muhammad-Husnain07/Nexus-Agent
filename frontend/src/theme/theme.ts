import { createTheme } from "@mui/material/styles";

declare module "@mui/material/styles" {
  interface PaletteOptions {
    role?: {
      tenant_admin: string;
      developer: string;
      end_user: string;
      viewer: string;
    };
  }
  interface Palette {
    role: {
      tenant_admin: string;
      developer: string;
      end_user: string;
      viewer: string;
    };
  }
}

export const getTheme = (mode: "light" | "dark") =>
  createTheme({
    palette: {
      mode,
      primary: { main: "#1976d2" },
      secondary: { main: "#9c27b0" },
      role: {
        tenant_admin: "#7b1fa2",
        developer: "#1565c0",
        end_user: "#2e7d32",
        viewer: "#616161",
      },
    },
    typography: {
      fontFamily: '"Inter", "Roboto", "Helvetica", "Arial", sans-serif',
    },
    shape: { borderRadius: 8 },
    components: {
      MuiCard: {
        styleOverrides: {
          root: { borderRadius: 12, boxShadow: mode === "dark"
            ? "0 2px 12px rgba(0,0,0,0.3)" : "0 2px 12px rgba(0,0,0,0.08)" },
        },
      },
      MuiButton: {
        styleOverrides: { root: { textTransform: "none", fontWeight: 600 } },
      },
      MuiDrawer: {
        styleOverrides: { paper: { border: "none" } },
      },
    },
  });
