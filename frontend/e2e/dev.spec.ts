import { expect, test } from "@playwright/test";

test("developer console route loads without inventing a run", async ({ page }) => {
  await page.goto("http://localhost:5173/dev");
  await expect(page.getByRole("heading", { name: "Developer Console" })).toBeVisible({ timeout: 30000 });
  await expect(page.getByText("No live event trail is available.")).toBeVisible({ timeout: 30000 });
});
