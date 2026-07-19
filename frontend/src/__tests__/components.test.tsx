import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { ThemeProvider } from "../theme/ThemeProvider";
import { Card, CardContent, Typography } from "@mui/material";

describe("MUI Components", () => {
  it("should render a card with content", () => {
    render(
      <ThemeProvider>
        <Card><CardContent><Typography>Hello</Typography></CardContent></Card>
      </ThemeProvider>
    );
    expect(screen.getByText("Hello")).toBeInTheDocument();
  });
});
