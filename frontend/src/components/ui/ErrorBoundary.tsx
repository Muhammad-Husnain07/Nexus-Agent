import { Component, type ReactNode } from "react";
import { Box, Alert, Button, Typography } from "@mui/material";

interface Props { children: ReactNode; }
interface State { hasError: boolean; error?: Error; }

export class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false };
  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }
  render() {
    if (this.state.hasError) {
      return (
        <Box sx={{ p: 4, textAlign: "center" }}>
          <Alert severity="error" sx={{ mb: 2 }}>
            <Typography variant="h6" gutterBottom>Something went wrong</Typography>
            <Typography variant="body2" sx={{ mb: 2 }}>{this.state.error?.message}</Typography>
            <Button variant="contained" onClick={() => this.setState({ hasError: false })}>Try Again</Button>
          </Alert>
        </Box>
      );
    }
    return this.props.children;
  }
}
