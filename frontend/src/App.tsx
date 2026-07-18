import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { BrowserRouter, Routes, Route } from "react-router-dom"
import { lazy, Suspense } from "react"

const Dashboard = lazy(() => import("@/pages/Dashboard"))
const ToolBuilder = lazy(() => import("@/pages/ToolBuilder"))
const TestPlayground = lazy(() => import("@/pages/TestPlayground"))
const Chat = lazy(() => import("@/pages/Chat"))
const EmbedGenerator = lazy(() => import("@/pages/EmbedGenerator"))

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 30_000, retry: 1 },
  },
})

function LoadingFallback() {
  return (
    <div className="flex items-center justify-center h-screen text-muted-foreground">
      Loading...
    </div>
  )
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Suspense fallback={<LoadingFallback />}>
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/tools/new" element={<ToolBuilder />} />
            <Route path="/tools/:id/edit" element={<ToolBuilder />} />
            <Route path="/test" element={<TestPlayground />} />
            <Route path="/chat" element={<Chat />} />
            <Route path="/embed" element={<EmbedGenerator />} />
          </Routes>
        </Suspense>
      </BrowserRouter>
    </QueryClientProvider>
  )
}
