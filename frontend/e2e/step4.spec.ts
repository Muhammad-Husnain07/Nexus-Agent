import { expect, test } from "@playwright/test";

/** FE Step 4: workflows, memory, widget studio. Requires seeded backend. */
const LIVE = process.env.NEXUS_E2E === "1";
const API = "http://localhost:8000/api/v1";

test.describe("Step 4 user surfaces", () => {
  test.skip(!LIVE, "NEXUS_E2E=1 required (seeded backend)");
  test.setTimeout(300000);

  test("workflow create -> activate -> instance read surface", async ({ page }) => {
    const suffix = crypto.randomUUID().slice(0, 8);
    const workflow = await page.request.post(`${API}/workflows`, {
      data: {
        name: `step4_e2e_${suffix}`,
        description: "Step 4 workflow acceptance",
        trigger_intent_pattern: `step4 workflow ${suffix}`,
        enabled: false,
        steps: [
          {
            id: "step_1",
            description: "Define orchestration",
            capability: "define_word",
            intent: "define orchestration",
            inputs: { word: "orchestration" },
          },
        ],
      },
    });
    expect(workflow.status()).toBe(201);
    const created = (await workflow.json()) as { id: string; version: number };
    const activate = await page.request.post(`${API}/workflows/${created.id}/activate`);
    expect(activate.status()).toBe(200);

    // The current backend exposes WorkflowInstance reads, but the audited
    // repository has no runtime writer for WorkflowInstance. Verify the
    // read contract and render either existing instances or the honest empty
    // state; instance creation remains a backend follow-up, not frontend
    // fabrication.
    const instancesResponse = await page.request.get(`${API}/workflows/${created.id}/instances`);
    expect(instancesResponse.status()).toBe(200);
    const instances = (await instancesResponse.json()) as { instances: unknown[]; count: number };
    expect(Array.isArray(instances.instances)).toBe(true);

    await page.goto(`http://localhost:5173/workflows/${created.id}`);
    await expect(page.getByText(`step4_e2e_${suffix}`)).toBeVisible({ timeout: 30000 });
    await expect(page.getByText("Active", { exact: true })).toBeVisible({ timeout: 30000 });
    await expect(page.getByText("Instances", { exact: true })).toBeVisible();
    if (instances.count === 0) {
      await expect(page.getByText("No instances for this workflow.")).toBeVisible();
    } else {
      await expect(page.locator("tbody tr").first()).toBeVisible({ timeout: 60000 });
    }
  });

  test("memory load -> search -> delete -> refresh", async ({ page }) => {
    const memoriesResponse = await page.request.get(`${API}/memory`);
    expect(memoriesResponse.ok()).toBeTruthy();
    const memories = (await memoriesResponse.json()) as Array<{ id: string; content: string }>;
    test.skip(memories.length === 0, "Seeded environment has no memory rows");
    const target = memories[0];
    const searchTerm = target.content.trim().split(/\s+/)[0].slice(0, 30);

    await page.goto("http://localhost:5173/memory");
    await expect(page.getByText(target.content.slice(0, 20))).toBeVisible({ timeout: 30000 });
    const search = page.getByPlaceholder("Search memories...").first();
    await search.fill(searchTerm);
    await expect(page.getByText(target.content.slice(0, 20))).toBeVisible({ timeout: 30000 });

    await page.getByRole("button", { name: "Delete memory" }).first().click();
    await expect(page.getByRole("heading", { name: "Delete Memory" })).toBeVisible();
    await page.getByRole("button", { name: "Delete", exact: true }).click();
    await expect(page.getByText(target.content.slice(0, 20))).not.toBeVisible({ timeout: 30000 });
    await page.reload();
    await expect(page.getByText(target.content.slice(0, 20))).not.toBeVisible({ timeout: 30000 });
  });

  test("widget configure -> validate -> generate embed snippet", async ({ page }) => {
    await page.goto("http://localhost:5173/widget");
    await expect(page.getByRole("heading", { name: "Widget Embed Studio" })).toBeVisible({ timeout: 30000 });
    await page.getByLabel("Widget title").fill("Step 4 Assistant");
    await page.getByRole("button", { name: "Validate configuration" }).click();
    await expect(page.getByText("Widget configuration is valid")).toBeVisible({ timeout: 10000 });
    await expect(page.locator("pre").first()).toContainText('data-title="Step 4 Assistant"');
    await expect(page.locator("pre").first()).toContainText("dist-embed/embed-widget.js");
  });
});
