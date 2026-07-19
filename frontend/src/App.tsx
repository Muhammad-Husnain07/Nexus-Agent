import { lazy, Suspense, useCallback } from "react";
import { BrowserRouter, Routes, Route, Navigate, useNavigate } from "react-router-dom";
import { QueryClientProvider } from "@tanstack/react-query";
import { SnackbarProvider } from "notistack";
import { queryClient } from "./lib/query-client";
import { ThemeProvider } from "./theme/ThemeProvider";
import { AuthProvider } from "./contexts/AuthContext";
import { ProtectedRoute } from "./components/ProtectedRoute";
import { ErrorBoundary } from "./components/UI/ErrorBoundary";
import { PageLoader } from "./components/UI/LoadingStates";
import DashboardLayout from "./components/Layout/DashboardLayout";
import CommandPalette from "./components/CommandPalette";
import { useCommandPaletteStore } from "./stores/command-palette-store";
import { useKeyPress } from "./hooks/use-key-press";

const Login = lazy(() => import("./pages/Login"));
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
const CostAnalytics = lazy(() => import("./pages/CostAnalytics"));
const Settings = lazy(() => import("./pages/Settings"));
const EmbedGenerator = lazy(() => import("./features/embed/EmbedGenerator"));
const EmbedTokens = lazy(() => import("./pages/EmbedTokens"));
const AdminTenants = lazy(() => import("./pages/AdminTenants"));
const AdminUsers = lazy(() => import("./pages/AdminUsers"));
const AdminApiKeys = lazy(() => import("./pages/AdminApiKeys"));

function AppContent() {
  const navigate = useNavigate();
  const { open: cmdOpen, setOpen: setCmdOpen, toggle: toggleCmd } = useCommandPaletteStore();
  const { setOpen: setCmdOpenAlt } = useCommandPaletteStore();

  useKeyPress({
    "Cmd+k": () => toggleCmd(),
    "Cmd+n": () => navigate("/chat"),
    "Cmd+t": () => navigate("/tools/new"),
    "Escape": () => { if (cmdOpen) setCmdOpen(false); },
  });

  return (
    <AuthProvider>
      <ErrorBoundary>
        <Suspense fallback={<PageLoader />}>
          <Routes>
            <Route path="/login" element={<Login />} />
            <Route element={<ProtectedRoute><DashboardLayout /></ProtectedRoute>}>
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
              <Route path="/cost-analytics" element={<CostAnalytics />} />
              <Route path="/settings" element={<Settings />} />
              <Route path="/embed" element={<EmbedGenerator />} />
              <Route path="/embed/tokens" element={<EmbedTokens />} />
              <Route path="/embed/chat" element={<div>Embedded Chat</div>} />
              <Route path="/test" element={<TestPlayground />} />
              <Route path="/admin/tenants" element={<ProtectedRoute requiredRole={["tenant_admin"]}><AdminTenants /></ProtectedRoute>} />
              <Route path="/admin/users" element={<ProtectedRoute requiredRole={["tenant_admin"]}><AdminUsers /></ProtectedRoute>} />
              <Route path="/admin/api-keys" element={<ProtectedRoute requiredRole={["tenant_admin"]}><AdminApiKeys /></ProtectedRoute>} />
            </Route>
          </Routes>
          <CommandPalette open={cmdOpen} onClose={() => setCmdOpenAlt(false)} />
        </Suspense>
      </ErrorBoundary>
    </AuthProvider>
  );
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <SnackbarProvider maxSnack={3} anchorOrigin={{ horizontal: "right", vertical: "top" }}>
          <BrowserRouter>
            <AppContent />
          </BrowserRouter>
        </SnackbarProvider>
      </ThemeProvider>
    </QueryClientProvider>
  );
}
