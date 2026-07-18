import { StrictMode } from "react"
import { createRoot } from "react-dom/client"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { BrowserRouter, Routes, Route } from "react-router-dom"
import ThemeProvider from "@/theme/ThemeProvider"
import Login from "@/features/auth/Login"
import ProtectedRoute from "@/routes/ProtectedRoute"
import AppLayout from "@/components/layout/AppLayout"
import ChatPage from "@/features/chat/ChatPage"
import SessionsPage from "@/features/sessions/SessionsPage"
import ToolsPage from "@/features/tools/ToolsPage"
import ApprovalsPage from "@/features/approvals/ApprovalsPage"
import ObservabilityPage from "@/features/observability/ObservabilityPage"
import SettingsPage from "@/features/settings/SettingsPage"
import "./index.css"

const KEY = import.meta.env.VITE_MUI_X_LICENSE_KEY as string | undefined
if (KEY) {
  import("@mui/x-license").then((mod: Record<string, unknown>) => {
    const fn = (mod as { unstable_setLicenseKey?: (k: string) => void }).unstable_setLicenseKey
    if (fn) fn(KEY)
  })
} else if (import.meta.env.DEV) {
  console.info("[MUI X] No license key set. Community features will work. Pro features will show watermark.")
}

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 30_000, retry: 1 },
  },
})

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ThemeProvider>
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
        </BrowserRouter>
      </QueryClientProvider>
    </ThemeProvider>
  </StrictMode>,
)
