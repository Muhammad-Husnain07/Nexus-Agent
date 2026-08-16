import { expect, test } from "@playwright/test";

/**
 * FE Step 3 tasks E2E — requires a LIVE backend + NIM + a running worker
 * (`python -m nexus.tasks`). Env-gated: NEXUS_E2E=1.
 */

const LIVE = process.env.NEXUS_E2E === "1";
const APP = "http://localhost:5173";
const API = "http://localhost:8000/api/v1";

test.describe("background tasks (live backend + worker)", () => {
  test.skip(!LIVE, "NEXUS_E2E=1 required (live backend + NIM + worker)");
  test.setTimeout(600000);

  test("start background task -> observe queued/running -> reload -> completed result", async ({
    page,
  }) => {
    // Create a session + background workflow_run task via the REST API.
    const create = await page.request.post(`${API}/sessions`, {
      data: { title: "Task e2e" },
    });
    expect(create.status()).toBe(201);
    const session = (await create.json()) as { id: string };
    const taskRes = await page.request.post(`${API}/tasks`, {
      data: {
        task_type: "workflow_run",
        session_id: session.id,
        payload: {
          execution_id: crypto.randomUUID(),
          session_id: session.id,
          message: "Get the weather in Lahore",
          execution_plan_version: 2,
          resolver_version: 1,
          planner_version: 1,
          compiler_version: 2,
        },
      },
    });
    expect(taskRes.status()).toBe(201);
    const task = (await taskRes.json()) as { id: string };

    await page.goto(`${APP}/tasks`);
    await expect(page.getByText("No tasks yet.")).not.toBeVisible({ timeout: 15000 });
    // The task row appears (queued or already running) — match by the
    // detail link href (the id is not rendered as plain text).
    const link = page.locator(`a[href*="/tasks/${task.id}"]`);
    await expect(link).toBeVisible({ timeout: 20000 });
    const row = page.locator(`tr:has(${`a[href*="/tasks/${task.id}"]`})`);
    await expect(row).toContainText(/queued|running|completed/i, { timeout: 120000 });

    // Refresh mid-flight: TanStack Query reconstructs from REST.
    await page.reload();
    await expect(page.locator(`a[href*="/tasks/${task.id}"]`)).toBeVisible({
      timeout: 20000,
    });

    // Wait for completion (worker drives queued -> running -> completed).
    await expect(row).toContainText(/completed|failed|cancelled/i, { timeout: 300000 });

    // Open the detail page and verify the final response rendered.
    await link.first().click();
    await expect(page.getByText("Result", { exact: true })).toBeVisible({ timeout: 30000 });
    await expect(page.getByTestId("task-result")).toContainText(/lahore|weather|retrieved|I retrieved/i, {
      timeout: 30000,
    });
  });
});
