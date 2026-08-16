import { lazy, Suspense, useEffect } from "react"
import { BrowserRouter, Routes, Route, Navigate, Link } from "react-router-dom"
import { QueryClientProvider } from "@tanstack/react-query"
import { Toaster } from "sonner"
import { TooltipProvider } from "@/components/ui/tooltip"
import { Button } from "@/components/ui/button"
import { queryClient } from "@/lib/query-client"
import { useThemeStore } from "@/store"
import { ErrorBoundary } from "@/components/error-boundary"
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
const Tasks = lazy(() => import("@/routes/tasks/index"))
const TaskDetail = lazy(() => import("@/routes/tasks/[id]"))

function Loading() {
  return <div className="flex items-center justify-center h-screen text-muted-foreground">Loading...</div>
}

function NotFound() {
  return (
    <div className="flex flex-col items-center justify-center h-screen gap-4 text-center">
      <h1 className="text-6xl font-bold text-muted-foreground/30">404</h1>
      <p className="text-muted-foreground">Page not found</p>
      <Button asChild variant="outline"><Link to="/dashboard">Go to Dashboard</Link></Button>
    </div>
  )
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
            <ErrorBoundary>
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
                  <Route path="/tasks" element={<Tasks />} />
                  <Route path="/tasks/:id" element={<TaskDetail />} />
                  <Route path="/settings" element={<Settings />} />
                  <Route path="/test" element={<Playground />} />
                </Route>
                <Route path="*" element={<NotFound />} />
              </Routes>
            </ErrorBoundary>
          </Suspense>
        </TooltipProvider>
      </BrowserRouter>
    </QueryClientProvider>
  )
}
