import { lazy, Suspense, useEffect } from "react"
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom"
import { QueryClientProvider } from "@tanstack/react-query"
import { Toaster } from "sonner"
import { TooltipProvider } from "@/components/ui/tooltip"
import { queryClient } from "@/lib/query-client"
import { useThemeStore } from "@/store"
import DashboardLayout from "@/components/Layout/dashboard-layout"

const Dashboard = lazy(() => import("@/routes/dashboard"))
const Chat = lazy(() => import("@/routes/chat"))
const ToolsList = lazy(() => import("@/routes/tools/index"))
const ToolDetail = lazy(() => import("@/routes/tools/[id]"))
const ToolNew = lazy(() => import("@/routes/tools/new"))
const Sessions = lazy(() => import("@/routes/sessions/index"))
const SessionDetail = lazy(() => import("@/routes/sessions/[id]"))
const Memory = lazy(() => import("@/routes/memory/index"))
const Playground = lazy(() => import("@/routes/playground/index"))
const Settings = lazy(() => import("@/routes/settings"))

function Loading() {
  return <div className="flex items-center justify-center h-screen text-muted-foreground">Loading...</div>
}

export default function App() {
  const theme = useThemeStore((s) => s.theme)
  const toggleTheme = useThemeStore((s) => s.toggleTheme)

  useEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark")
  }, [theme])

  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <TooltipProvider delayDuration={300}>
          <Toaster position="top-right" richColors />
          <Suspense fallback={<Loading />}>
            <Routes>
              <Route element={<DashboardLayout dark={theme === "dark"} onToggle={toggleTheme} />}>
                <Route path="/" element={<Navigate to="/dashboard" replace />} />
                <Route path="/dashboard" element={<Dashboard />} />
                <Route path="/chat" element={<Chat />} />
                <Route path="/tools" element={<ToolsList />} />
                <Route path="/tools/new" element={<ToolNew />} />
                <Route path="/tools/:id" element={<ToolDetail />} />
                <Route path="/tools/:id/edit" element={<ToolNew />} />
                <Route path="/sessions" element={<Sessions />} />
                <Route path="/sessions/:id" element={<SessionDetail />} />
                <Route path="/memory" element={<Memory />} />
                <Route path="/settings" element={<Settings />} />
                <Route path="/test" element={<Playground />} />
              </Route>
            </Routes>
          </Suspense>
        </TooltipProvider>
      </BrowserRouter>
    </QueryClientProvider>
  )
}
