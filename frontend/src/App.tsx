import { lazy, Suspense } from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { QueryClientProvider } from "@tanstack/react-query";
import { SnackbarProvider } from "notistack";
import { queryClient } from "./lib/query-client";
import { ThemeProvider } from "./theme/ThemeProvider";
import { ErrorBoundary } from "./components/UI/ErrorBoundary";
import { PageLoader } from "./components/UI/LoadingStates";
import DashboardLayout from "./components/Layout/DashboardLayout";

const Dashboard = lazy(() => import("./pages/Dashboard"));
const Chat = lazy(() => import("./pages/Chat"));
const ToolsList = lazy(() => import("./pages/ToolsList"));
const ToolDetail = lazy(() => import("./pages/ToolDetail"));
const ToolBuilder = lazy(() => import("./features/tool-builder/ToolBuilderForm"));
const TestPlayground = lazy(() => import("./features/test-playground/TestPlayground"));
const Sessions = lazy(() => import("./pages/Sessions"));
const SessionDetail = lazy(() => import("./pages/SessionDetail"));
const Approvals = lazy(() => import("./pages/Approvals"));
const Memory = lazy(() => import("./pages/Memory"));
const EmbedGenerator = lazy(() => import("./features/embed/EmbedGenerator"));

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <SnackbarProvider maxSnack={3} anchorOrigin={{ horizontal: "right", vertical: "top" }}>
          <BrowserRouter>
            <ErrorBoundary>
              <Suspense fallback={<PageLoader />}>
                <Routes>
                  <Route element={<DashboardLayout />}>
                    <Route path="/" element={<Navigate to="/dashboard" replace />} />
                    <Route path="/dashboard" element={<Dashboard />} />
                    <Route path="/chat" element={<Chat />} />
                    <Route path="/tools" element={<ToolsList />} />
                    <Route path="/tools/new" element={<ToolBuilder />} />
                    <Route path="/tools/:id" element={<ToolDetail />} />
                    <Route path="/tools/:id/edit" element={<ToolBuilder />} />
                    <Route path="/sessions" element={<Sessions />} />
                    <Route path="/sessions/:id" element={<SessionDetail />} />
                    <Route path="/approvals" element={<Approvals />} />
                    <Route path="/memory" element={<Memory />} />
                    <Route path="/embed" element={<EmbedGenerator />} />
                    <Route path="/test" element={<TestPlayground />} />
                  </Route>
                </Routes>
              </Suspense>
            </ErrorBoundary>
          </BrowserRouter>
        </SnackbarProvider>
      </ThemeProvider>
    </QueryClientProvider>
  );
}
