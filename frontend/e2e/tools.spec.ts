import { test, expect } from "@playwright/test";

test.describe("Tools Management", () => {
  test("should show tools list page", async ({ page }) => {
    await page.goto("/tools");
    await expect(page.locator("body")).toBeVisible();
  });
});
