import { test, expect } from "@playwright/test";

test.describe("Chat", () => {
  test("should show chat interface", async ({ page }) => {
    // Navigate directly to chat (will be redirected if unauthenticated)
    await page.goto("/chat");
    // Should at least load without crashing
    await expect(page.locator("body")).toBeVisible();
  });
});
