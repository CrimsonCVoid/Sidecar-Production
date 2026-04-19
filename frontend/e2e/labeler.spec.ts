import { test, expect, Page, Route } from "@playwright/test";

// Fixture: mock API base URL
const API_BASE = "http://localhost:8000";

// Helper: mock all API routes with defaults
async function mockApi(
  page: Page,
  overrides?: {
    getLabels?: (route: Route) => Promise<void>;
    saveLabels?: (route: Route) => Promise<void>;
    snapPreview?: (route: Route) => Promise<void>;
    errors?: (route: Route) => Promise<void>;
  },
) {
  // GET/POST /api/labels/* -> default responses
  await page.route(`${API_BASE}/api/labels/*`, async (route) => {
    if (route.request().method() === "GET") {
      if (overrides?.getLabels) return overrides.getLabels(route);
      await route.fulfill({
        status: 404,
        contentType: "application/json",
        body: JSON.stringify({
          detail: "No labels found for sample test-sample",
        }),
      });
    } else if (route.request().method() === "POST") {
      if (overrides?.saveLabels) return overrides.saveLabels(route);
      const body = JSON.parse(route.request().postData() || "{}");
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          status: "saved",
          sample_id: body.sample_id || "test-sample",
          panel_count: body.panels?.length || 0,
        }),
      });
    }
  });

  // POST /api/snap/preview -> mock feature graph
  await page.route(`${API_BASE}/api/snap/preview`, async (route) => {
    if (overrides?.snapPreview) return overrides.snapPreview(route);
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        feature_graph: {
          features: [
            {
              id: 0,
              valence: 2,
              position_xyz: [100, 0, 0],
              panel_ids: [0, 1],
            },
            {
              id: 1,
              valence: 2,
              position_xyz: [100, 100, 0],
              panel_ids: [0, 1],
            },
          ],
          edges: [{ panel_a: 0, panel_b: 1, feature_ids: [0, 1] }],
        },
        snapped_polygons: {
          "0": [
            [0, 0, 0],
            [100, 0, 0],
            [100, 100, 0],
            [0, 100, 0],
          ],
          "1": [
            [100, 0, 0],
            [200, 0, 0],
            [200, 100, 0],
            [100, 100, 0],
          ],
        },
      }),
    });
  });

  // POST /api/errors -> 200 (fire-and-forget)
  await page.route(`${API_BASE}/api/errors`, async (route) => {
    if (overrides?.errors) return overrides.errors(route);
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ status: "logged" }),
    });
  });

  // GET /api/hillshade/* -> mock 1x1 PNG to avoid image load failures
  await page.route(`${API_BASE}/api/hillshade/*`, async (route) => {
    // Minimal 1x1 transparent PNG
    const pngBuffer = Buffer.from(
      "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
      "base64",
    );
    await route.fulfill({
      status: 200,
      contentType: "image/png",
      body: pngBuffer,
    });
  });
}

// Helper: get store state from window
async function getStoreState(page: Page) {
  return page.evaluate(() => {
    const store = window.__labeler_store;
    if (!store) return null;
    const state = store.getState();
    return {
      panels: state.panels,
      activeDrawing: state.activeDrawing,
      mode: state.mode,
    };
  });
}

test.describe("Labeler", () => {
  test("label-save-reload: draw triangle, save, verify API call", async ({
    page,
  }) => {
    let saveRequest: { body: string } | null = null;

    await mockApi(page, {
      saveLabels: async (route) => {
        saveRequest = { body: route.request().postData() || "" };
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            status: "saved",
            sample_id: "test-sample",
            panel_count: 1,
          }),
        });
      },
    });

    await page.goto("/labeling/test-sample");

    // Wait for canvas to be present
    const canvas = page.locator("[data-testid='labeler-canvas'] canvas");
    await canvas.waitFor({ state: "visible", timeout: 15000 });

    // Draw a triangle: 3 clicks
    await canvas.click({ position: { x: 100, y: 100 } });
    await canvas.click({ position: { x: 200, y: 100 } });
    await canvas.click({ position: { x: 150, y: 200 } });
    // Click near first vertex to auto-close (within 10px)
    await canvas.click({ position: { x: 100, y: 100 } });

    // Verify panel was created in store
    const stateAfterDraw = await getStoreState(page);
    expect(stateAfterDraw).not.toBeNull();
    expect(stateAfterDraw!.panels).toHaveLength(1);

    // Click Save Labels
    await page.getByRole("button", { name: "Save Labels" }).click();

    // Verify save toast appears
    await expect(page.getByText(/Labels saved/)).toBeVisible({ timeout: 5000 });

    // Verify the save request body has the expected shape
    expect(saveRequest).not.toBeNull();
    const savedData = JSON.parse(saveRequest!.body);
    expect(savedData.panels).toHaveLength(1);
    expect(savedData.panels[0].corners_pix).toHaveLength(3);
  });

  test("undo-redo: draw vertices, undo, redo, verify state", async ({
    page,
  }) => {
    await mockApi(page);
    await page.goto("/labeling/test-sample");

    const canvas = page.locator("[data-testid='labeler-canvas'] canvas");
    await canvas.waitFor({ state: "visible", timeout: 15000 });

    // Place 3 vertices (no auto-close -- just building activeDrawing)
    await canvas.click({ position: { x: 50, y: 50 } });
    await canvas.click({ position: { x: 150, y: 50 } });
    await canvas.click({ position: { x: 100, y: 150 } });

    // Verify 3 vertices in activeDrawing
    let state = await getStoreState(page);
    expect(state!.activeDrawing).toHaveLength(3);

    // Undo last vertex
    await page.keyboard.press("Meta+z");

    // Verify 2 vertices remain
    state = await getStoreState(page);
    expect(state!.activeDrawing).toHaveLength(2);

    // Redo
    await page.keyboard.press("Meta+Shift+z");

    // Verify back to 3 vertices
    state = await getStoreState(page);
    expect(state!.activeDrawing).toHaveLength(3);
  });

  test("magnet-snap-override: snap to nearby vertex, shift bypasses", async ({
    page,
  }) => {
    // Pre-load a panel via mock GET /labels
    await mockApi(page, {
      getLabels: async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            sample_id: "test-sample",
            panels: [
              {
                id: 0,
                corners_pix: [
                  [100, 100],
                  [200, 100],
                  [200, 200],
                  [100, 200],
                ],
              },
            ],
          }),
        });
      },
    });

    await page.goto("/labeling/test-sample");
    const canvas = page.locator("[data-testid='labeler-canvas'] canvas");
    await canvas.waitFor({ state: "visible", timeout: 15000 });

    // Wait for labels to load into store
    await page.waitForFunction(() => {
      const store = window.__labeler_store;
      if (!store) return false;
      return store.getState().panels.length === 1;
    });

    // Click at (105, 105) -- within 12px of existing vertex (100, 100)
    // Without Shift: should snap to (100, 100)
    await canvas.click({ position: { x: 105, y: 105 } });

    let state = await getStoreState(page);
    const drawing1 = state!.activeDrawing;
    // The snapped vertex should be at [100, 100] (the existing panel vertex)
    expect(drawing1).not.toBeNull();
    expect(drawing1![0][0]).toBe(100);
    expect(drawing1![0][1]).toBe(100);

    // Undo the vertex placement
    await page.keyboard.press("Meta+z");

    // Now click at same position WITH Shift held -- should NOT snap
    await canvas.click({ position: { x: 105, y: 105 }, modifiers: ["Shift"] });

    state = await getStoreState(page);
    const drawing2 = state!.activeDrawing;
    expect(drawing2).not.toBeNull();
    // With Shift, vertex should be at the cursor position (105, 105), not snapped
    expect(drawing2![0][0]).toBe(105);
    expect(drawing2![0][1]).toBe(105);
  });

  test("auto-close: polygon closes when clicking near first vertex", async ({
    page,
  }) => {
    await mockApi(page);
    await page.goto("/labeling/test-sample");

    const canvas = page.locator("[data-testid='labeler-canvas'] canvas");
    await canvas.waitFor({ state: "visible", timeout: 15000 });

    // Draw 3 vertices
    await canvas.click({ position: { x: 100, y: 100 } });
    await canvas.click({ position: { x: 200, y: 100 } });
    await canvas.click({ position: { x: 150, y: 200 } });

    // Verify activeDrawing has 3 vertices
    let state = await getStoreState(page);
    expect(state!.activeDrawing).toHaveLength(3);
    expect(state!.panels).toHaveLength(0);

    // Click within 10px of first vertex (100, 100) to auto-close
    await canvas.click({ position: { x: 103, y: 103 } });

    // Verify polygon closed: activeDrawing is null, panels has 1 entry
    state = await getStoreState(page);
    expect(state!.activeDrawing).toBeNull();
    expect(state!.panels).toHaveLength(1);
  });

  test("error capture: unhandled error is forwarded to /api/errors", async ({
    page,
  }) => {
    let errorPayload: Record<string, unknown> | null = null;

    await mockApi(page, {
      errors: async (route) => {
        errorPayload = JSON.parse(route.request().postData() || "{}");
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ status: "logged" }),
        });
      },
    });

    await page.goto("/labeling/test-sample");

    // Wait for page to be fully loaded
    const canvas = page.locator("[data-testid='labeler-canvas'] canvas");
    await canvas.waitFor({ state: "visible", timeout: 15000 });

    // Trigger an unhandled error in the browser
    await page.evaluate(() => {
      setTimeout(() => {
        throw new Error("Test unhandled error for E2E");
      }, 100);
    });

    // Wait for the error to be captured and sent
    await page.waitForTimeout(2000);

    // Verify the error was forwarded to /api/errors
    expect(errorPayload).not.toBeNull();
    expect(errorPayload!.error_type).toBe("unhandled_exception");
    expect(errorPayload!.message).toContain("Test unhandled error for E2E");
    expect(errorPayload!.page).toBe("/labeling/test-sample");
  });
});
