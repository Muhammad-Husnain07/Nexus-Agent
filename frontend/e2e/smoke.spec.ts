import { test, expect } from "@playwright/test";

test("landing page renders and routes to dashboard", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveURL(/\/dashboard/);
  await expect(page.getByRole("heading", { level: 1 }).first()).toBeVisible();
});

test("sidebar navigation is available", async ({ page }) => {
  await page.goto("/dashboard");
  await expect(page.getByRole("navigation")).toBeVisible();
});
