# Phase 5: Labeling Dashboard - Research

**Researched:** 2026-04-19
**Domain:** Next.js App Router + Konva canvas polygon labeler with Zustand state, API integration, browser error capture, Playwright E2E tests
**Confidence:** HIGH

## Summary

Phase 5 builds the first Next.js frontend for this project -- there is no existing frontend code. The labeling dashboard is a single-route canvas-dominant application (`/labeling/[sampleId]`) where users draw roof panel polygons on a hillshade image, with shared-node snapping to eliminate ridge drift at the source. The page communicates with the Phase 4 FastAPI sidecar via three endpoints: `POST /api/snap/preview`, `POST /api/labels/{sampleId}`, and `GET /api/labels/{sampleId}`.

The core technical challenges are: (1) setting up a new Next.js project from scratch with shadcn, Tailwind, and TypeScript; (2) integrating react-konva in a Next.js App Router context where Konva cannot run server-side; (3) implementing the shared-node magnet algorithm for snapping vertices across panels; (4) wiring Zustand + zundo for undo/redo with correct partialize to exclude UI-only state from history; (5) Playwright E2E testing of canvas interactions where standard DOM locators do not work -- tests must use coordinate-based clicking and state inspection.

**Primary recommendation:** Use `next/dynamic` with `ssr: false` for all Konva canvas components. Build the Next.js app in a `frontend/` subdirectory colocated with the existing Python pipeline. Pin Next.js 15.x (not 16.x) for React 18 compatibility with the broader shadcn/konva ecosystem to minimize peer dependency friction. Use coordinate-based Playwright clicks with `data-testid` attributes on the Konva container for E2E canvas testing.

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| DASH-01 | Per-sample labeling route (`/labeling/[sampleId]`) with Konva canvas on hillshade | Next.js app router dynamic route + react-konva Stage/Layer + use-image for hillshade loading. Hillshade needs a server-side render endpoint or pre-generated PNG in Supabase Storage. |
| DASH-02 | Shared-node magnet (12px snap radius, shift-click override, visual indicator) | Custom `findNearestVertex()` function checking Euclidean distance in pixel space. Shift key detected via `e.evt.shiftKey` on Konva event. Yellow ring indicator as Konva Circle. |
| DASH-03 | Undo/redo via Zustand + zundo, Cmd+Z / Cmd+Shift+Z | zundo `temporal` middleware wrapping store, `partialize` to exclude UI state (mode, selectedPanelIndex, snapPreview, isSaving, isLoadingPreview). Keyboard handler via `useEffect` with `keydown` listener. |
| DASH-04 | Snap preview mode with valence-colored feature dots | Calls `POST /api/snap/preview` with PanelsInput body, validates response with Zod SnapPreviewResponseSchema, renders FeatureNode positions as Konva Circles with valence-based color/radius. |
| DASH-05 | Output mask.json compatible with `polygons_from_clicks` | Serialize `PanelData[]` to PanelsInput-compatible JSON. Zod PanelsInputSchema validates before POST. Must match PanelCorners Pydantic schema exactly (id: int, corners_pix: float[][]). |
| DASH-06 | Auto-close polygon when cursor within 10px of first vertex | Distance check on `onMouseMove` against first vertex of `activeDrawing`. Green ring Konva Circle indicator. On click within 10px, call `closePolygon()` action. |
| OBSERVABILITY-01b | Browser-side error capture to backend logging endpoint | `window.addEventListener("error"/"unhandledrejection")` in a root layout ErrorBoundary. POST to new `/api/errors` endpoint on FastAPI sidecar. Requires adding the errors endpoint to the Python API. |
| TESTING-01a | Playwright E2E tests for labeler flows (min 3 tests) | Playwright `page.locator('canvas').click({position: {x, y}})` for canvas interaction. API mocking via `page.route()` for deterministic tests. Visual regression via `toHaveScreenshot()` optional. |
</phase_requirements>

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Polygon drawing + editing | Browser / Client (Konva canvas) | -- | Pure client-side interaction; canvas API has no server equivalent |
| Shared-node magnet (snap) | Browser / Client | -- | Pixel-space distance calculation, real-time cursor feedback |
| Undo/redo state | Browser / Client (Zustand) | -- | In-memory temporal state, session-scoped |
| Snap preview (topology) | API / Backend (FastAPI) | Browser / Client (overlay) | Snap engine runs server-side; browser renders the result |
| Label persistence | API / Backend (FastAPI + Supabase) | Browser / Client (fetch) | Data stored in Supabase `labels` table; browser calls API |
| Hillshade image | API / Backend (render) or CDN/Storage | Browser / Client (display) | DSM is a GeoTIFF; hillshade must be pre-rendered to PNG server-side |
| Error capture | Browser / Client (capture) | API / Backend (logging) | Browser captures; backend logs structured JSON |
| E2E testing | Browser / Client (Playwright) | -- | Tests exercise the full client stack |

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| next | 15.5.15 | App router, SSR, routing | [VERIFIED: npm registry] Stable LTS release. Next.js 16.x requires React 19; react-konva 19 also requires React 19. However, pinning 15.x avoids early-adoption issues with React 19 peer deps in the wider shadcn ecosystem. If React 19 peer deps resolve cleanly at install time, 16.x is acceptable. |
| react | 19.2.5 | UI rendering | [VERIFIED: npm registry] Required by react-konva 19.x peer deps |
| react-dom | 19.2.5 | DOM rendering | [VERIFIED: npm registry] Paired with react |
| react-konva | 19.2.3 | Declarative Konva canvas | [VERIFIED: npm registry] React bindings for Konva; peer deps: konva ^8-10, react ^19 |
| konva | 10.2.5 | Canvas 2D graphics engine | [VERIFIED: npm registry] v10 drops Node.js canvas dep; reduces SSR friction |
| zustand | 5.0.12 | State management | [VERIFIED: npm registry] Minimal, hook-based, no boilerplate |
| zundo | 2.3.0 | Undo/redo temporal middleware | [VERIFIED: npm registry] zundo for zustand undo/redo |
| zod | 4.3.6 | API boundary validation | [VERIFIED: npm registry] TypeScript-first schema validation |
| @supabase/supabase-js | 2.103.3 | Supabase client for label persistence | [VERIFIED: npm registry] Official JS client |
| typescript | ~5.7 | Type safety | [ASSUMED] Current stable TS; Next.js 15 ships with TS support |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| use-image | 1.1.4 | Konva image loader hook | [VERIFIED: npm registry] Loading hillshade PNG into Konva Image component |
| sonner | 2.0.7 | Toast notifications | [VERIFIED: npm registry] shadcn toast component uses sonner under the hood |
| @playwright/test | 1.59.1 | E2E browser testing | [VERIFIED: npm registry] Canvas interaction testing via coordinate clicks |
| lucide-react | latest | Icon library | [ASSUMED] Bundled with shadcn; used for toolbar icons |
| tailwindcss | 4.x | Utility CSS | [ASSUMED] shadcn requires Tailwind; v4 is current default with Next.js 15 |
| next/font/google | built-in | Inter font loading | [VERIFIED: Next.js docs] No extra dependency; built into Next.js |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| react-konva | fabric.js | Fabric has richer built-in tools but heavier bundle, worse React integration |
| zustand + zundo | Redux + redux-undo | Redux is more boilerplate; zustand is simpler for this scope |
| Playwright | Cypress | Cypress has weaker canvas support; Playwright's coordinate click API is better for canvas |
| sonner | react-hot-toast | sonner is shadcn's official toast; consistency with design system |

**Installation:**

```bash
# Create Next.js app (if not exists)
npx create-next-app@15 frontend --ts --tailwind --eslint --app --src-dir

# Core deps
cd frontend
npm install react-konva konva use-image zustand zundo zod @supabase/supabase-js sonner

# Dev deps
npm install -D @playwright/test
npx playwright install chromium
```

**shadcn initialization:**

```bash
npx shadcn@latest init
# Select: neutral/zinc base, CSS variables mode
npx shadcn@latest add button tooltip badge separator toast alert-dialog dropdown-menu
```

**Version verification:**

| Package | Verified Version | Registry Date |
|---------|-----------------|---------------|
| next | 15.5.15 (latest 15.x) | 2026-04-19 |
| react | 19.2.5 | 2026-04-19 |
| react-konva | 19.2.3 | 2026-04-19 |
| konva | 10.2.5 | 2026-04-19 |
| zustand | 5.0.12 | 2026-04-19 |
| zundo | 2.3.0 | 2026-04-19 |
| zod | 4.3.6 | 2026-04-19 |
| @supabase/supabase-js | 2.103.3 | 2026-04-19 |
| @playwright/test | 1.59.1 | 2026-04-19 |
| sonner | 2.0.7 | 2026-04-19 |
| use-image | 1.1.4 | 2026-04-19 |

## Architecture Patterns

### System Architecture Diagram

```
User Browser
    |
    v
[Next.js App Router] -----> /labeling/[sampleId] (client component)
    |
    +--- [Konva Stage] <--- hillshade PNG (from Supabase Storage)
    |       |
    |       +--- [PolygonLayer] - completed polygons
    |       +--- [DrawingLayer] - in-progress polyline
    |       +--- [SnapPreviewLayer] - valence dots
    |       +--- [MagnetIndicator] - yellow ring
    |       +--- [AutoCloseIndicator] - green ring
    |
    +--- [Zustand Store] <---> [zundo temporal] (undo/redo history)
    |       |
    |       +--- panels: PanelData[]
    |       +--- activeDrawing: number[][] | null
    |       +--- mode, selectedPanelIndex, snapPreview (UI, not tracked)
    |
    +--- [API Client (fetch + Zod)] ----> FastAPI Sidecar (localhost:8000)
    |       |
    |       +--- POST /api/snap/preview   -> snap engine -> feature graph
    |       +--- POST /api/labels/{id}    -> Supabase labels table
    |       +--- GET  /api/labels/{id}    -> load saved panels
    |       +--- POST /api/errors         -> structured error log
    |
    +--- [Error Boundary] ----> POST /api/errors (browser error capture)
```

### Recommended Project Structure

```
frontend/
  src/
    app/
      layout.tsx              # Root layout: Inter font, Toaster, ErrorBoundary
      page.tsx                # Redirect to /labeling or landing (minimal)
      labeling/
        [sampleId]/
          page.tsx            # Dynamic route: loads labeling page
    components/
      canvas/
        HillshadeCanvas.tsx   # Konva Stage wrapper (dynamic import, ssr: false)
        PolygonLayer.tsx      # Completed polygon rendering
        DrawingLayer.tsx      # In-progress polyline + vertices
        SnapPreviewLayer.tsx  # Valence-colored feature dots
        MagnetIndicator.tsx   # Yellow snap ring
        AutoCloseIndicator.tsx # Green auto-close ring
      ui/                     # shadcn components (auto-generated)
        button.tsx
        tooltip.tsx
        badge.tsx
        separator.tsx
        toast.tsx / sonner.tsx
        alert-dialog.tsx
      labeling/
        LabelingHeader.tsx    # Back button + title + Save CTA
        LabelingToolbar.tsx   # Mode buttons, undo/redo, delete, snap preview
    lib/
      api.ts                  # Fetch wrapper with Zod validation + error capture
      schemas.ts              # Zod schemas mirroring Pydantic models
      supabase.ts             # Supabase client singleton
      errors.ts               # Browser error capture setup
    stores/
      labeler-store.ts        # Zustand + zundo store
    hooks/
      use-keyboard-shortcuts.ts  # Cmd+Z, Cmd+Shift+Z, Escape, D, S, Delete
      use-canvas-size.ts         # Responsive canvas dimensions
  e2e/
    labeler.spec.ts           # Playwright E2E: label-save-reload, undo-redo, magnet-snap
  playwright.config.ts
  next.config.ts              # Canvas external config for webpack
```

### Pattern 1: Dynamic Import for Konva (SSR bypass)

**What:** Konva requires a DOM with `window` and `HTMLCanvasElement`. Next.js App Router renders server-side by default. Konva components must be dynamically imported with SSR disabled.
**When to use:** Every component that imports from `react-konva` or `konva`.
**Example:**

```typescript
// Source: react-konva README + Next.js docs on dynamic imports
// [VERIFIED: react-konva GitHub issues #832, #787]

// src/app/labeling/[sampleId]/page.tsx
"use client";

import dynamic from "next/dynamic";

const HillshadeCanvas = dynamic(
  () => import("@/components/canvas/HillshadeCanvas"),
  { ssr: false }
);

export default function LabelingPage({
  params,
}: {
  params: { sampleId: string };
}) {
  return (
    <div className="flex flex-col h-screen bg-zinc-950">
      <LabelingHeader sampleId={params.sampleId} />
      <LabelingToolbar />
      <div className="flex-1">
        <HillshadeCanvas sampleId={params.sampleId} />
      </div>
    </div>
  );
}
```

### Pattern 2: Zustand + zundo Store with partialize

**What:** Zustand store with temporal middleware for undo/redo, excluding UI-only state from history.
**When to use:** The labeler store is the single source of truth for panel data.
**Example:**

```typescript
// Source: zundo README [VERIFIED: Context7 /charkour/zundo]
// src/stores/labeler-store.ts
import { create } from "zustand";
import { temporal } from "zundo";

interface PanelData {
  id: number;
  corners_pix: number[][];
}

interface LabelerState {
  panels: PanelData[];
  activeDrawing: number[][] | null;
  mode: "draw" | "select";
  selectedPanelIndex: number | null;
  snapPreview: SnapPreviewData | null;
  isSaving: boolean;
  isLoadingPreview: boolean;
  // Actions
  addVertex: (x: number, y: number) => void;
  closePolygon: () => void;
  deletePanel: (index: number) => void;
  setMode: (mode: "draw" | "select") => void;
  selectPanel: (index: number | null) => void;
  setSnapPreview: (data: SnapPreviewData | null) => void;
  loadPanels: (panels: PanelData[]) => void;
  cancelDrawing: () => void;
}

export const useLabelerStore = create<LabelerState>()(
  temporal(
    (set, get) => ({
      panels: [],
      activeDrawing: null,
      mode: "draw",
      selectedPanelIndex: null,
      snapPreview: null,
      isSaving: false,
      isLoadingPreview: false,

      addVertex: (x, y) =>
        set((state) => ({
          activeDrawing: state.activeDrawing
            ? [...state.activeDrawing, [x, y]]
            : [[x, y]],
          snapPreview: null, // clear preview on edit
        })),

      closePolygon: () =>
        set((state) => {
          if (!state.activeDrawing || state.activeDrawing.length < 3) {
            return { activeDrawing: null };
          }
          const newPanel: PanelData = {
            id: state.panels.length,
            corners_pix: state.activeDrawing,
          };
          return {
            panels: [...state.panels, newPanel],
            activeDrawing: null,
            snapPreview: null,
          };
        }),

      deletePanel: (index) =>
        set((state) => ({
          panels: state.panels.filter((_, i) => i !== index),
          selectedPanelIndex: null,
          snapPreview: null,
        })),

      // ... other actions
    }),
    {
      // Only track panels + activeDrawing in undo history
      partialize: (state) => ({
        panels: state.panels,
        activeDrawing: state.activeDrawing,
      }),
    }
  )
);
```

### Pattern 3: Konva Polygon Drawing with Magnet Snap

**What:** Drawing handler that checks for nearby existing vertices and snaps.
**When to use:** The `onMouseDown` handler of the Konva Stage in draw mode.
**Example:**

```typescript
// Source: Konva events docs [VERIFIED: Context7 /konvajs/site]
// Magnet snap algorithm [ASSUMED based on UI-SPEC requirements]

const MAGNET_RADIUS_PX = 12;
const AUTOCLOSE_RADIUS_PX = 10;

function findNearestVertex(
  point: { x: number; y: number },
  panels: PanelData[],
  excludePanelIndex?: number
): { vertex: number[]; distance: number } | null {
  let nearest: { vertex: number[]; distance: number } | null = null;
  for (let i = 0; i < panels.length; i++) {
    if (i === excludePanelIndex) continue;
    for (const corner of panels[i].corners_pix) {
      const dx = point.x - corner[0];
      const dy = point.y - corner[1];
      const dist = Math.sqrt(dx * dx + dy * dy);
      if (dist < MAGNET_RADIUS_PX && (!nearest || dist < nearest.distance)) {
        nearest = { vertex: corner, distance: dist };
      }
    }
  }
  return nearest;
}

// In the Stage onMouseDown handler:
const handleStageClick = (e: KonvaEventObject<MouseEvent>) => {
  const stage = e.target.getStage();
  if (!stage) return;
  const pos = stage.getPointerPosition();
  if (!pos) return;

  const shiftHeld = e.evt.shiftKey;
  let placeX = pos.x;
  let placeY = pos.y;

  if (!shiftHeld) {
    const snap = findNearestVertex(pos, panels);
    if (snap) {
      placeX = snap.vertex[0];
      placeY = snap.vertex[1];
    }
  }

  // Check auto-close
  if (activeDrawing && activeDrawing.length >= 3) {
    const first = activeDrawing[0];
    const dx = pos.x - first[0];
    const dy = pos.y - first[1];
    if (Math.sqrt(dx * dx + dy * dy) < AUTOCLOSE_RADIUS_PX) {
      closePolygon();
      return;
    }
  }

  addVertex(placeX, placeY);
};
```

### Pattern 4: Zod Schema Mirroring Pydantic

**What:** TypeScript Zod schemas that exactly mirror the Python Pydantic models.
**When to use:** Every API call boundary.
**Example:**

```typescript
// Source: UI-SPEC Zod Schemas section + schemas.py [VERIFIED: codebase]
// src/lib/schemas.ts
import { z } from "zod";

export const PanelCornersSchema = z.object({
  id: z.number().int(),
  corners_pix: z.array(z.array(z.number()).length(2)).min(3),
});

export const PanelsInputSchema = z.object({
  panels: z.array(PanelCornersSchema),
  res_m: z.number().nullable().optional(),
  shape: z.array(z.number().int()).nullable().optional(),
  panel_count: z.number().int().nullable().optional(),
  panel_pixel_counts: z.record(z.string(), z.number().int()).nullable().optional(),
});

export const FeatureNodeSchema = z.object({
  id: z.number().int(),
  valence: z.number().int(),
  position_xyz: z.array(z.number()).length(3).nullable(),
  panel_ids: z.array(z.number().int()),
});

export const SnapPreviewResponseSchema = z.object({
  feature_graph: z.object({
    features: z.array(FeatureNodeSchema),
    edges: z.array(
      z.object({
        panel_a: z.number().int(),
        panel_b: z.number().int(),
        feature_ids: z.array(z.number().int()),
      })
    ),
  }),
  snapped_polygons: z.record(z.string(), z.array(z.array(z.number()))),
});

export const LabelDataSchema = z.object({
  sample_id: z.string(),
  panels: z.array(PanelCornersSchema),
});

export type PanelCorners = z.infer<typeof PanelCornersSchema>;
export type PanelsInput = z.infer<typeof PanelsInputSchema>;
export type SnapPreviewResponse = z.infer<typeof SnapPreviewResponseSchema>;
export type LabelData = z.infer<typeof LabelDataSchema>;
```

### Pattern 5: next.config.ts for Konva Compatibility

**What:** Webpack external config to prevent "Can't resolve 'canvas'" error.
**When to use:** Required in next.config.ts for any Next.js project using Konva.
**Example:**

```typescript
// Source: react-konva GitHub issue #832 [VERIFIED: GitHub]
// next.config.ts
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  webpack: (config) => {
    config.externals = [...(config.externals || []), { canvas: "canvas" }];
    return config;
  },
};

export default nextConfig;
```

### Anti-Patterns to Avoid

- **Importing react-konva in server components:** Causes "window is not defined" crash. Always use `"use client"` + `dynamic(() => import(...), { ssr: false })`. [VERIFIED: react-konva GitHub issues]
- **Tracking UI state in undo history:** Mode, selected panel, loading flags should NOT be in zundo's tracked state. Use `partialize` to exclude them. [VERIFIED: zundo docs]
- **Using Turbopack with Konva:** Turbopack has unresolved canvas module resolution issues. Remove `--turbopack` flag from dev script. [VERIFIED: react-konva issue #832]
- **Hand-rolling polygon ID assignment:** Panel IDs must be stable integers matching the Python `PanelCorners.id` field. Incrementing from `panels.length` is fragile if panels are deleted. Use a monotonic counter in the store.
- **Storing canvas coordinates as transformed (scaled/panned) values:** Always store raw pixel coordinates relative to the hillshade image. Apply stage transforms only for display. Panning/zooming changes the stage transform, not the stored coordinates.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Canvas 2D polygon rendering | Custom Canvas API calls | react-konva `<Line closed>` | Declarative, event handling built-in, React lifecycle |
| Undo/redo state machine | Custom stack-based undo | zundo temporal middleware | Handles edge cases (branching, partialize, serialization) |
| Toast notifications | Custom notification system | shadcn toast (sonner) | Accessible, animated, queued, shadcn-themed |
| Confirmation dialogs | Custom modal | shadcn AlertDialog | Accessible, focus trap, keyboard handling |
| Image loading for canvas | Manual `new Image()` + onload | `use-image` hook | Handles loading states, errors, caching |
| Schema validation | Manual type guards | Zod schemas | Runtime + compile-time safety, error messages |
| API response parsing | `JSON.parse` + manual checks | Zod `.safeParse()` | Type-safe parsing with structured errors |

**Key insight:** The canvas interaction layer (Konva) and the state layer (Zustand) are both well-established libraries with thousands of production users. Custom solutions for canvas rendering or undo/redo would be the highest-risk code in the entire phase.

## Common Pitfalls

### Pitfall 1: react-konva SSR Crash

**What goes wrong:** Importing react-konva in a server component or without dynamic import causes `ReferenceError: window is not defined` at build time.
**Why it happens:** Konva depends on `window`, `document`, and `HTMLCanvasElement` which don't exist in Node.js.
**How to avoid:** Every file that imports from `react-konva` must be dynamically imported with `ssr: false`. The page component itself can be `"use client"` but the canvas component should still use `dynamic()`.
**Warning signs:** Build fails with "window is not defined" or "Can't resolve 'canvas'".

### Pitfall 2: Schema Drift Between Pydantic and Zod

**What goes wrong:** The Python PanelCorners Pydantic model and the TypeScript Zod PanelCornersSchema diverge silently. Requests that pass Zod validation fail Python validation (or vice versa).
**Why it happens:** Two schema definitions in two languages with no automated sync. The Pydantic model has a `strip_close_polygon_duplicate` field_validator that Zod cannot replicate.
**How to avoid:** Define Zod schemas by reading `schemas.py` and `schema.py` directly. Add a comment `// Mirrors: roof_pipeline/panel_snap_v2/schema.py` in the Zod file. The Pydantic dedup validator is server-side only -- the Zod schema should enforce `min(3)` on corners but does NOT need to strip duplicates.
**Warning signs:** 422 errors from the API that pass client-side validation.

### Pitfall 3: Undo State Explosion from Rapid Edits

**What goes wrong:** Mouse move events during drawing create hundreds of undo states per second, making undo useless (each undo step is a single pixel move).
**Why it happens:** zundo records state on every `set()` call by default.
**How to avoid:** Only track `addVertex` and `closePolygon` in undo history, not mouse move position updates. The UI-SPEC states undo actions are: vertex placement, polygon completion, polygon deletion. Mouse cursor position is NOT an undo action. Keep the cursor position in local React state, not in the Zustand store.
**Warning signs:** Pressing Cmd+Z many times appears to do nothing (each step is sub-pixel).

### Pitfall 4: Canvas Coordinate Transform Confusion

**What goes wrong:** Polygon coordinates are stored in screen space (after pan/zoom) instead of image space. When the user zooms in and draws, the polygon appears offset when zoomed back out.
**Why it happens:** `stage.getPointerPosition()` returns absolute stage coordinates. When the stage is scaled/panned, these need to be transformed back to image coordinates.
**How to avoid:** Use `layer.getRelativePointerPosition()` or manually transform: `imageX = (stageX - stage.x()) / stage.scaleX()`. Store all coordinates in image pixel space. Apply stage transform only for rendering.
**Warning signs:** Polygons drift or jump when panning/zooming the canvas.

### Pitfall 5: Playwright Canvas Testing

**What goes wrong:** Standard Playwright locators (`getByRole`, `getByText`) cannot find Konva shapes inside a canvas element. Tests that try to click on a "polygon" by selector fail.
**Why it happens:** Canvas renders pixels, not DOM elements. Konva shapes exist in Konva's internal scene graph, not the DOM.
**How to avoid:** Test canvas interactions using coordinate-based clicks: `page.locator('canvas').click({ position: { x: 100, y: 200 } })`. Verify state through the store (expose store on `window.__labeler_store` in dev) or via API responses. Add `data-testid` to the Konva Stage container div for reliable locator targeting.
**Warning signs:** `page.getByRole('button')` works for toolbar but cannot interact with canvas content.

### Pitfall 6: Hillshade Image Not Available

**What goes wrong:** The hillshade image URL is undefined or returns 404. The canvas loads empty with no visual feedback.
**Why it happens:** The existing pipeline generates hillshade images server-side via matplotlib. There is no pre-rendered hillshade PNG stored in Supabase Storage. The DSM (GeoTIFF) is stored but browsers cannot render GeoTIFF.
**How to avoid:** Either (a) add a hillshade generation step to the pipeline run that saves a PNG alongside the mesh/PDF outputs, or (b) add a `/api/hillshade/{sampleId}` endpoint that renders the DSM to PNG on demand. Option (a) is preferred -- the pipeline already uploads outputs to Supabase Storage.
**Warning signs:** Empty canvas background, "Image failed to load" errors.

### Pitfall 7: Panel ID Reuse After Deletion

**What goes wrong:** Deleting panel ID 2 then creating a new panel reuses ID 2. The API receives panels with duplicate IDs across save/reload cycles.
**Why it happens:** Using `panels.length` as the ID counter resets when panels are deleted.
**How to avoid:** Use a monotonic counter (`nextPanelId`) in the store that only increments, never decreases. Persist it across the session.
**Warning signs:** Duplicate panel IDs in saved label data; snap preview shows incorrect panel associations.

## Code Examples

### Fetch Wrapper with Zod Validation

```typescript
// Source: Project conventions (TypeScript, Zod at every boundary)
// src/lib/api.ts

import { z } from "zod";
import { SnapPreviewResponseSchema, LabelDataSchema } from "./schemas";
import type { PanelsInput, LabelData, SnapPreviewResponse } from "./schemas";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public traceId?: string
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function apiFetch<T>(
  path: string,
  schema: z.ZodType<T>,
  options?: RequestInit
): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...options?.headers,
    },
  });

  if (!res.ok) {
    const traceId = res.headers.get("X-Trace-ID") ?? undefined;
    const body = await res.json().catch(() => ({ message: res.statusText }));
    throw new ApiError(res.status, body.message || body.detail || res.statusText, traceId);
  }

  const data = await res.json();
  return schema.parse(data);
}

export async function getLabels(sampleId: string): Promise<LabelData> {
  return apiFetch(`/api/labels/${sampleId}`, LabelDataSchema);
}

export async function saveLabels(sampleId: string, panels: PanelCorners[]): Promise<void> {
  await fetch(`${API_BASE}/api/labels/${sampleId}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ sample_id: sampleId, panels }),
  });
}

export async function snapPreview(panels: PanelsInput): Promise<SnapPreviewResponse> {
  return apiFetch("/api/snap/preview", SnapPreviewResponseSchema, {
    method: "POST",
    body: JSON.stringify(panels),
  });
}
```

### Browser Error Capture (OBSERVABILITY-01b)

```typescript
// Source: UI-SPEC Error Capture Contract
// src/lib/errors.ts

interface BrowserError {
  timestamp: string;
  page: string;
  error_type: "unhandled_exception" | "unhandled_rejection" | "api_error" | "render_error";
  message: string;
  stack: string | null;
  user_agent: string;
  sample_id: string | null;
}

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

function reportError(error: BrowserError): void {
  // Fire-and-forget; don't let error reporting cause more errors
  fetch(`${API_BASE}/api/errors`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(error),
    keepalive: true,
  }).catch(() => {});
}

export function initErrorCapture(sampleId: string | null): () => void {
  const onError = (event: ErrorEvent) => {
    reportError({
      timestamp: new Date().toISOString(),
      page: window.location.pathname,
      error_type: "unhandled_exception",
      message: event.message,
      stack: event.error?.stack ?? null,
      user_agent: navigator.userAgent,
      sample_id: sampleId,
    });
  };

  const onRejection = (event: PromiseRejectionEvent) => {
    reportError({
      timestamp: new Date().toISOString(),
      page: window.location.pathname,
      error_type: "unhandled_rejection",
      message: String(event.reason),
      stack: event.reason?.stack ?? null,
      user_agent: navigator.userAgent,
      sample_id: sampleId,
    });
  };

  window.addEventListener("error", onError);
  window.addEventListener("unhandledrejection", onRejection);

  return () => {
    window.removeEventListener("error", onError);
    window.removeEventListener("unhandledrejection", onRejection);
  };
}
```

### Konva Zoom/Pan with Wheel

```typescript
// Source: Konva zoom sandbox [VERIFIED: Context7 /konvajs/site]

const SCALE_BY = 1.05;
const MIN_SCALE = 0.1;
const MAX_SCALE = 10;

function handleWheel(e: KonvaEventObject<WheelEvent>) {
  e.evt.preventDefault();
  const stage = e.target.getStage();
  if (!stage) return;

  const oldScale = stage.scaleX();
  const pointer = stage.getPointerPosition();
  if (!pointer) return;

  const mousePointTo = {
    x: (pointer.x - stage.x()) / oldScale,
    y: (pointer.y - stage.y()) / oldScale,
  };

  const direction = e.evt.deltaY > 0 ? -1 : 1;
  const newScale = Math.min(MAX_SCALE, Math.max(MIN_SCALE,
    direction > 0 ? oldScale * SCALE_BY : oldScale / SCALE_BY
  ));

  stage.scale({ x: newScale, y: newScale });
  stage.position({
    x: pointer.x - mousePointTo.x * newScale,
    y: pointer.y - mousePointTo.y * newScale,
  });
}
```

### Playwright Canvas Test Pattern

```typescript
// Source: Playwright canvas testing patterns [VERIFIED: Playwright docs]
// e2e/labeler.spec.ts

import { test, expect } from "@playwright/test";

test.describe("Labeler", () => {
  test("label-save-reload: draw polygon, save, reload, verify persist", async ({
    page,
  }) => {
    // Mock API responses
    await page.route("**/api/labels/test-sample", async (route) => {
      if (route.request().method() === "GET") {
        await route.fulfill({
          status: 404,
          body: JSON.stringify({ detail: "No labels found" }),
        });
      } else {
        await route.fulfill({
          status: 200,
          body: JSON.stringify({ status: "saved", panel_count: 1 }),
        });
      }
    });

    await page.goto("/labeling/test-sample");

    // Draw a triangle on the canvas using coordinate clicks
    const canvas = page.locator("[data-testid='labeler-canvas'] canvas");
    await canvas.click({ position: { x: 100, y: 100 } });
    await canvas.click({ position: { x: 200, y: 100 } });
    await canvas.click({ position: { x: 150, y: 200 } });
    // Close polygon by clicking near first vertex
    await canvas.click({ position: { x: 100, y: 100 } });

    // Save
    await page.getByRole("button", { name: "Save Labels" }).click();

    // Verify toast
    await expect(page.getByText("Labels saved")).toBeVisible();
  });

  test("undo-redo: draw, undo vertex, redo, verify state", async ({
    page,
  }) => {
    await page.goto("/labeling/test-sample");
    const canvas = page.locator("[data-testid='labeler-canvas'] canvas");

    // Place 2 vertices
    await canvas.click({ position: { x: 100, y: 100 } });
    await canvas.click({ position: { x: 200, y: 100 } });

    // Undo last vertex
    await page.keyboard.press("Meta+z");

    // Redo
    await page.keyboard.press("Meta+Shift+z");

    // Verify via exposed store state or visual state
  });
});
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| react-konva with webpack canvas workaround | Konva v10 drops Node.js canvas dep | Konva 10.0.0 | Simpler config, but `next.config.ts` webpack external still recommended as safety net |
| zustand v4 middleware chaining | zustand v5 simplified middleware API | zustand 5.0 | `temporal()` wraps `create()` directly, no `devtools` order issues |
| zod v3 | zod v4 (4.3.6) | 2025 | New `.min()`, `.length()` combinators; same core API |
| Next.js Pages Router | Next.js App Router (stable since 13.4) | 2023 | Server Components by default; client components need `"use client"` |
| shadcn v0 (CLI) | shadcn v2+ (`npx shadcn@latest`) | 2024 | Registry-based component installation; cleaner CLI |

**Deprecated/outdated:**
- `react-konva` versions < 18: Do not support React 18/19 hooks
- `zustand` v3: Old API without `create()()` double-call pattern
- `next/dynamic` with `loading` prop in Pages Router: App Router uses `Suspense` instead, but `ssr: false` is still the same

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | The `samples` table in Supabase has an `id` column and a `dsm_path` column pointing to Supabase Storage | Architecture Patterns | HIGH -- if no DSM is stored in Storage, hillshade cannot be generated or loaded. Need to confirm samples table schema with user. |
| A2 | Hillshade PNG will need to be pre-generated and stored in Supabase Storage; there is no existing hillshade image endpoint | Pitfalls / DASH-01 | HIGH -- if no hillshade is available, the canvas has no background. May need a new FastAPI endpoint or pipeline step. |
| A3 | The Next.js frontend will live in a `frontend/` subdirectory, not in a separate repo | Project Structure | LOW -- colocating frontend and backend in one repo is standard for MVP. If user wants a separate repo, structure moves but code stays the same. |
| A4 | TypeScript ~5.7 ships with Next.js 15 | Standard Stack | LOW -- exact TS version doesn't affect the plan; Next.js bundles its own TS. |
| A5 | Next.js 15.x is preferred over 16.x for peer dependency stability | Standard Stack | MEDIUM -- if user already has a React 19 preference and all peer deps resolve, 16.x is fine. The core code is identical. |
| A6 | The FastAPI sidecar runs on localhost:8000 during development | Code Examples | LOW -- API_BASE is configurable via env var. |
| A7 | Playwright will test against a locally running dev server | Testing | LOW -- standard Playwright + Next.js dev setup. |

## Open Questions

1. **Hillshade image source**
   - What we know: The pipeline generates hillshade via matplotlib `_shaded_relief()` from DSM data. DSM files are in Supabase Storage. There is no pre-rendered hillshade PNG.
   - What's unclear: How does the frontend get a hillshade PNG? Does the pipeline already upload one? Or do we need to add a `/api/hillshade/{sampleId}` endpoint?
   - Recommendation: Add a hillshade PNG generation step to the existing pipeline run (`run_pipeline` in `pipeline.py`), uploading it to Supabase Storage alongside the other outputs. The frontend fetches the Storage URL directly. This avoids adding a render endpoint.

2. **Supabase `labels` table schema**
   - What we know: Phase 4 created a stub `labels` endpoint with columns `sample_id`, `panels` (jsonb), `updated_at`. D-07 says Phase 5 owns the schema.
   - What's unclear: Is the table already created in Supabase, or does Phase 5 need to create it?
   - Recommendation: Phase 5 should assume the table needs creation (SQL migration). The Phase 4 stub endpoint already uses the right column names, so the schema matches.

3. **Supabase client in Next.js**
   - What we know: FastAPI uses `supabase-py` server-side. The frontend needs `@supabase/supabase-js` for direct Storage access (hillshade image URL).
   - What's unclear: Should the frontend talk to Supabase directly (for Storage URL generation) or only through the FastAPI proxy?
   - Recommendation: Frontend calls FastAPI for all data operations (labels, snap preview). For hillshade images, use a Supabase Storage public URL if the bucket is public, or use a signed URL from the API. Avoid direct Supabase client in the frontend for MVP simplicity.

4. **FastAPI `/api/errors` endpoint for OBSERVABILITY-01b**
   - What we know: The UI-SPEC defines a `POST /api/errors` endpoint for browser error capture. This endpoint does not exist in the Phase 4 API code.
   - What's unclear: Should this be added as part of Phase 5, or is it out of scope?
   - Recommendation: Add a simple `/api/errors` endpoint to the FastAPI sidecar in the first plan of Phase 5. It only needs to log the incoming JSON payload as a structured log line using the existing logging middleware.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Node.js | Next.js, npm | Yes | v25.9.0 | -- |
| npm | Package management | Yes | 11.12.1 | -- |
| npx | shadcn init, create-next-app | Yes | 11.12.1 | -- |
| Playwright browsers | E2E tests | No (not installed) | -- | `npx playwright install chromium` in setup |
| Python 3.11+ | FastAPI sidecar (dev server) | Yes (assumed from prior phases) | -- | -- |
| FastAPI sidecar running | API calls | No (must start manually) | -- | Mock API in tests; dev instructions in README |

**Missing dependencies with no fallback:**
- None blocking

**Missing dependencies with fallback:**
- Playwright browsers: Install via `npx playwright install chromium` as part of test setup (Wave 0 task)

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | @playwright/test 1.59.1 |
| Config file | `frontend/playwright.config.ts` (Wave 0 creation) |
| Quick run command | `npx playwright test --project=chromium e2e/labeler.spec.ts` |
| Full suite command | `npx playwright test` |

### Phase Requirements to Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| DASH-01 | Page loads with hillshade and saved polygons | E2E | `npx playwright test e2e/labeler.spec.ts -g "load"` | No -- Wave 0 |
| DASH-02 | Magnet snap within 12px, Shift override | E2E | `npx playwright test e2e/labeler.spec.ts -g "magnet"` | No -- Wave 0 |
| DASH-03 | Undo/redo with Cmd+Z/Cmd+Shift+Z | E2E | `npx playwright test e2e/labeler.spec.ts -g "undo"` | No -- Wave 0 |
| DASH-04 | Snap preview overlay with valence dots | E2E | `npx playwright test e2e/labeler.spec.ts -g "snap preview"` | No -- Wave 0 |
| DASH-05 | Save outputs mask.json compatible with polygons_from_clicks | E2E | `npx playwright test e2e/labeler.spec.ts -g "save"` | No -- Wave 0 |
| DASH-06 | Auto-close polygon at 10px from first vertex | E2E | `npx playwright test e2e/labeler.spec.ts -g "auto-close"` | No -- Wave 0 |
| OBSERVABILITY-01b | Browser errors captured and forwarded | E2E | `npx playwright test e2e/labeler.spec.ts -g "error"` | No -- Wave 0 |
| TESTING-01a | Playwright tests exist and pass | E2E | `npx playwright test` | No -- Wave 0 |

### Sampling Rate

- **Per task commit:** `npx playwright test --project=chromium e2e/labeler.spec.ts`
- **Per wave merge:** `npx playwright test`
- **Phase gate:** Full suite green before `/gsd-verify-work`

### Wave 0 Gaps

- [ ] `frontend/` -- entire Next.js project scaffold
- [ ] `frontend/playwright.config.ts` -- Playwright configuration
- [ ] `frontend/e2e/labeler.spec.ts` -- E2E test file for labeler flows
- [ ] `npx playwright install chromium` -- browser binary for test runner
- [ ] `frontend/src/lib/schemas.ts` -- Zod schemas (shared between app and tests)

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No | MVP is single-user; no auth in Phase 5 |
| V3 Session Management | No | No sessions; stateless API calls |
| V4 Access Control | No | Single-user MVP; no RBAC |
| V5 Input Validation | Yes | Zod at every API boundary (frontend); Pydantic at every API boundary (backend) |
| V6 Cryptography | No | No secrets stored client-side |

### Known Threat Patterns for Next.js + Konva + Supabase

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| XSS via crafted polygon data | Tampering | Zod validation strips unexpected fields; Konva renders to canvas (not innerHTML) |
| CORS bypass to FastAPI sidecar | Spoofing | FastAPI CORS middleware allows only `http://localhost:3000` by default |
| API abuse (snap preview is CPU-bound) | Denial of Service | Rate limiting not required for single-user MVP; `asyncio.to_thread` prevents event loop blocking |
| Schema injection via label save | Tampering | Pydantic `strict=True, extra="forbid"` on backend; Zod on frontend |
| Error payload leak (stack traces) | Information Disclosure | Browser error capture sends to own backend; no third-party Sentry; FastAPI exception handlers strip tracebacks from HTTP responses |

## Sources

### Primary (HIGH confidence)

- [npm registry] -- Verified versions: next 15.5.15/16.2.4, react 19.2.5, react-konva 19.2.3, konva 10.2.5, zustand 5.0.12, zundo 2.3.0, zod 4.3.6, @supabase/supabase-js 2.103.3, @playwright/test 1.59.1, sonner 2.0.7, use-image 1.1.4
- [Context7 /charkour/zundo] -- zundo temporal middleware API, partialize pattern, reactive temporal hook
- [Context7 /konvajs/react-konva] -- Stage, Layer, Line, Circle components, event handling, refs
- [Context7 /konvajs/site] -- Polygon (closed Line), pointer position, zoom/pan wheel handler, image loading
- [Context7 /pmndrs/zustand] -- partialize middleware, persist, store creation patterns

### Secondary (MEDIUM confidence)

- [react-konva GitHub issue #832](https://github.com/konvajs/react-konva/issues/832) -- Canvas module resolution fix for Next.js 15.2.3+, Turbopack incompatibility
- [react-konva GitHub issue #787](https://github.com/konvajs/react-konva/issues/787) -- Dynamic import pattern for Next.js 14+
- [shadcn installation docs](https://ui.shadcn.com/docs/installation/next) -- shadcn init command for Next.js
- [Next.js docs: Server and Client Components](https://nextjs.org/docs/app/getting-started/server-and-client-components) -- `"use client"` directive

### Tertiary (LOW confidence)

- Playwright canvas testing patterns -- coordinate-based click approach verified from multiple community sources but no official Konva + Playwright integration guide exists

## Project Constraints (from CLAUDE.md)

- **TypeScript everywhere, no `any`:** All frontend code must be fully typed. No `any` escape hatches.
- **Zod at every API boundary:** Every `fetch()` response must be validated through a Zod schema before use.
- **Next.js app router:** Use App Router, not Pages Router.
- **Python 3.11 backend:** FastAPI sidecar uses Python 3.11; any new endpoint (like `/api/errors`) follows existing patterns.
- **No new deps in pipeline module:** The `/api/errors` endpoint is in the `api/` subpackage, not the pipeline module. Allowed.
- **Downstream stability:** Any changes to API endpoints or schemas.py must not break existing Phase 4 test suite.
- **Supabase schema:** New tables allowed if justified. The `labels` table is justified per D-07.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- all versions verified against npm registry; peer dependencies confirmed compatible
- Architecture: HIGH -- patterns verified from official docs and Context7; SSR bypass pattern well-documented
- Pitfalls: HIGH -- each pitfall sourced from GitHub issues, official docs, or codebase analysis
- Testing: MEDIUM -- Playwright canvas testing has no Konva-specific official guide; coordinate-based approach is the community standard

**Research date:** 2026-04-19
**Valid until:** 2026-05-19 (30 days -- stable libraries, unlikely to change)
