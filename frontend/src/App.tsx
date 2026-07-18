import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { BrowserRouter, Routes, Route } from "react-router-dom"
import { Toaster } from "sonner"
import { CssVarsProvider, CssBaseline, ThemeProvider } from "@mui/material"
import { SnackbarProvider } from "notistack"
import Login from "@/features/auth/Login"
import ProtectedRoute from "@/routes/ProtectedRoute"
import AppLayout from "@/components/layout/AppLayout"
import ChatPage from "@/features/chat/ChatPage"
import SessionsPage from "@/features/sessions/SessionsPage"
import ToolsPage from "@/features/tools/ToolsPage"
import ApprovalsPage from "@/features/approvals/ApprovalsPage"
import ObservabilityPage from "@/features/observability/ObservabilityPage"
import SettingsPage from "@/features/settings/SettingsPage"
import { cssVarsTheme, lightTheme, darkTheme } from "@/features/theme/muiTheme"
import { useThemeStore } from "@/features/theme/themeStore"

const queryClient = new QueryClient()

function ThemedApp() {
  const mode = useThemeStore((s) => s.mode)

  return (
    <CssVarsProvider theme={cssVarsTheme}>
      <ThemeProvider theme={mode === "dark" ? darkTheme : lightTheme}>
        <CssBaseline />
        <SnackbarProvider maxSnack={3} anchorOrigin={{ vertical: "bottom", horizontal: "right" }}>
        <QueryClientProvider client={queryClient}>
          <BrowserRouter>
            <Routes>
              <Route path="/login" element={<Login />} />
              <Route path="/" element={<ProtectedRoute><AppLayout /></ProtectedRoute>}>
                <Route index element={<ChatPage />} />
                <Route path="chat/:sessionId" element={<ChatPage />} />
                <Route path="sessions" element={<SessionsPage />} />
                <Route path="tools" element={<ToolsPage />} />
                <Route path="approvals" element={<ApprovalsPage />} />
                <Route path="observability" element={<ObservabilityPage />} />
                <Route path="settings" element={<SettingsPage />} />
              </Route>
            </Routes>
            <Toaster richColors />
          </BrowserRouter>
        </QueryClientProvider>
      </SnackbarProvider>
      </ThemeProvider>
    </CssVarsProvider>
  )
}

export default function App() {
  return <ThemedApp />
}
