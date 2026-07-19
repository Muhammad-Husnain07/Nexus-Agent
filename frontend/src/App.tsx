import { lazy, Suspense, useEffect, useState } from "react"
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom"
import { QueryClientProvider } from "@tanstack/react-query"
import { Toaster } from "sonner"
import { queryClient } from "@/lib/query-client"
import DashboardLayout from "@/components/layout/dashboard-layout"

const Dashboard = lazy(() => import("@/routes/dashboard"))
const Chat = lazy(() => import("@/routes/chat"))
const ToolsList = lazy(() => import("@/routes/tools/index"))
const ToolDetail = lazy(() => import("@/routes/tools/[id]"))
const ToolNew = lazy(() => import("@/routes/tools/new"))
const Sessions = lazy(() => import("@/routes/sessions/index"))
const SessionDetail = lazy(() => import("@/routes/sessions/[id]"))
const Approvals = lazy(() => import("@/routes/approvals/index"))
const Memory = lazy(() => import("@/routes/memory/index"))
const Playground = lazy(() => import("@/routes/playground/index"))
const Embed = lazy(() => import("@/routes/embed/index"))

function Loading() {
  return <div className="flex items-center justify-center h-screen text-muted-foreground">Loading...</div>
}

export default function App() {
  const [dark, setDark] = useState(() => localStorage.getItem("theme") === "dark")
  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark)
    localStorage.setItem("theme", dark ? "dark" : "light")
  }, [dark])

  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Toaster position="top-right" richColors />
        <Suspense fallback={<Loading />}>
          <Routes>
            <Route element={<DashboardLayout dark={dark} onToggle={() => setDark(!dark)} />}>
              <Route path="/" element={<Navigate to="/dashboard" replace />} />
              <Route path="/dashboard" element={<Dashboard />} />
              <Route path="/chat" element={<Chat />} />
              <Route path="/tools" element={<ToolsList />} />
              <Route path="/tools/new" element={<ToolNew />} />
              <Route path="/tools/:id" element={<ToolDetail />} />
              <Route path="/tools/:id/edit" element={<ToolNew />} />
              <Route path="/sessions" element={<Sessions />} />
              <Route path="/sessions/:id" element={<SessionDetail />} />
              <Route path="/approvals" element={<Approvals />} />
              <Route path="/memory" element={<Memory />} />
              <Route path="/embed" element={<Embed />} />
              <Route path="/test" element={<Playground />} />
            </Route>
          </Routes>
        </Suspense>
      </BrowserRouter>
    </QueryClientProvider>
  )
}
