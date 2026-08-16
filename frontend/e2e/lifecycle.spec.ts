import { expect, test } from "@playwright/test";

/**
 * FE Step 2 lifecycle E2E — requires a LIVE backend + NIM endpoint.
 * Run locally with: NEXUS_E2E=1 npx playwright test e2e/lifecycle.spec.ts
 * (skipped otherwise — the PR job runs only the smoke suite).
 */

const LIVE = process.env.NEXUS_E2E === "1";
const APP = "http://localhost:5173";

test.describe("chat lifecycle (live backend)", () => {
  test.skip(!LIVE, "NEXUS_E2E=1 required (live backend + NIM)");
  test.setTimeout(420000);

  test("happy path: send query -> plan -> execute -> final response", async ({ page }) => {
    await page.goto(`${APP}/chat`);
    await page.getByRole("button", { name: "New Chat" }).first().click();
    const input = page.getByPlaceholder("Ask anything...");
    await expect(input).toBeVisible({ timeout: 15000 });
    await input.fill("Get the pokemon pikachu and describe its type.");
    await input.press("Enter");

    // Phase stepper appears (planning/executing).
    await expect(page.getByText(/Executing operations|Planning/).first()).toBeVisible({
      timeout: 60000,
    });
    // A tool row for the pokemon capability appears.
    await expect(page.getByText("get_pokemon").first()).toBeVisible({ timeout: 120000 });
    // Final text arrives (response content).
    await expect(page.getByText(/Pikachu/i).first()).toBeVisible({ timeout: 180000 });
  });

  test("refresh during run: state reconstructs and run completes server-side", async ({ page }) => {
    await page.goto(`${APP}/chat`);
    await page.getByRole("button", { name: "New Chat" }).first().click();
    const input = page.getByPlaceholder("Ask anything...");
    await expect(input).toBeVisible({ timeout: 15000 });
    // Two tools: the run outlives the refresh on a healthy endpoint.
    await input.fill("Get the weather in Lahore and search books by Jane Austen.");
    await input.press("Enter");
    await expect(page.getByText(/Executing operations|Planning/).first()).toBeVisible({
      timeout: 60000,
    });
    // The session must be in the URL (browser disposable -> reconstructable).
    await expect(page).toHaveURL(/session=/, { timeout: 10000 });

    // Refresh mid-run: the browser is disposable — the server continues.
    await page.reload();
    // After reload: either the run is still observed (banner) or it already
    // completed (final text rendered from reconstruction) — both valid.
    await expect(
      page
        .getByTestId("run-final-text")
        .or(
          page
            .getByText(/Run in progress|Executing operations|Complete|Partially complete|Timed out|Failed/)
            .first(),
        ),
    ).toBeVisible({ timeout: 30000 });
    // The run eventually finishes server-side and the reconstructed final
    // text renders; a wall-time timeout is accepted as endpoint variance
    // (the terminal banner above asserts it).
    await expect(page.getByTestId("run-final-text")).toBeVisible({ timeout: 240000 });
  });

  test("cancel: stop button cancels the run", async ({ page }) => {
    await page.goto(`${APP}/chat`);
    await page.getByRole("button", { name: "New Chat" }).first().click();
    const input = page.getByPlaceholder("Ask anything...");
    await expect(input).toBeVisible({ timeout: 15000 });
    await input.fill(
      "Give me a compact global intelligence report: for Lahore, Tokyo, Paris, London and New York find coordinates, weather and reverse geocode; retrieve country summaries for Pakistan, Japan and France; search anime and manga for Naruto, One Piece and Bleach; find books by Jane Austen and Charles Dickens; search recipes for chicken, pasta and rice; get docker information for nginx, redis and postgres.",
    );
    await input.press("Enter");
    await expect(page.getByText(/Executing operations/).first()).toBeVisible({
      timeout: 120000,
    });
    await page.getByRole("button", { name: /Stop/ }).click();
    await expect(page.getByText(/Cancelled|Timed out|Interrupted|Failed/).first()).toBeVisible({
      timeout: 60000,
    });
  });
});
