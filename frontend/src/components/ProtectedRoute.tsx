import { Navigate, useLocation } from "react-router-dom";
import { Box, CircularProgress, Alert } from "@mui/material";
import { useAuth } from "../contexts/AuthContext";

interface Props {
  children: React.ReactNode;
  requiredRole?: string[];
}

export function ProtectedRoute({ children, requiredRole }: Props) {
  const { isAuthenticated, isLoading, user } = useAuth();
  const location = useLocation();

  if (isLoading) {
    return (
      <Box display="flex" justifyContent="center" alignItems="center" minHeight="100vh">
        <CircularProgress />
      </Box>
    );
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" state={{ from: location }} replace />;
  }

  if (requiredRole && user && !requiredRole.includes(user.role)) {
    return (
      <Box display="flex" justifyContent="center" alignItems="center" minHeight="100vh">
        <Alert severity="error" sx={{ maxWidth: 400 }}>
          Access Denied. You need one of the following roles: {requiredRole.join(", ")}.
        </Alert>
      </Box>
    );
  }

  return <>{children}</>;
}
