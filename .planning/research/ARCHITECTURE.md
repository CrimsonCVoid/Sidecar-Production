# Architecture -- Milestone 2

**Domain:** FastAPI sidecar + Konva labeling dashboard + Supabase Realtime monitoring
**Researched:** 2026-04-19
**Confidence:** HIGH (existing codebase and Milestone 1 engine fully examined; library APIs Context7-verified)

## Context

Milestone 1 delivered the `panel_snap_v2` subpackage inside `roof_pipeline/`. The engine is a pure Python module with no HTTP, no framework dependencies -- just scipy, numpy, shapely. It exposes `snap_polygons(polygons, planes, tol)` returning snapped polygons and a feature graph. It is integrated in `run_real.py` behind `--snap-v2`. 41 tests passing.

Milestone 2 adds three new architectural components on top of this validated engine:
1. A FastAPI sidecar that wraps the engine for HTTP access
2. A Next.js Konva labeling canvas that replaces the matplotlib CLI labeler
3. Supabase Realtime pipeline monitoring bridging the sidecar and dashboard

---

## System Overview

```
                    NEXT.JS APP (My Metal Roofer)
                    ============================
  /labeling/[sampleId]            /labeling (index)
  +--------------------+   +------------------------------+
  |  Konva Canvas      |   |  Sample Table + Filter Chips |
  |  +-------------+   |   |  Run Monitor (Realtime)      |
  |  | DSM Image   |   |   +----------+-------------------+
  |  | + Polygons   |   |              |
  |  | + Magnets    |   |              |
  |  +------+------+   |              |
  |  Zustand + zundo   |              | Supabase Realtime
  |  (panels, history) |              | (pipeline_runs changes)
  +------+-------------+              |
         |                            |
         | POST /snap-preview         |
         | POST /run-pipeline         |
         v                            v
  +----------------------------------------------------+
  |            FASTAPI SIDECAR (DigitalOcean)           |
  |                                                     |
  |  /snap-preview   /run-pipeline   /labels/{id}       |
  |  (sync <500ms)   (background)    (CRUD)             |
  |       |               |              |              |
  |       v               v              v              |
  |  +---------------------------------------------+   |
  |  |        panel_snap_v2 (Milestone 1)           |   |
  |  |  winding -> cluster -> graph -> solver       |   |
  |  |  -> densify -> validate                      |   |
  |  +---------------------------------------------+   |
  |       |               |                             |
  |       v               v                             |
  |  EXISTING PIPELINE (planes -> boundaries ->         |
  |  mesh -> cutsheets -> shop_drawings)                |
  +-------------------+--------------------------------+
                      |
                      | supabase-py writes status rows
                      v
  +----------------------------------------------------+
  |                   SUPABASE                          |
  |                                                     |
  |  Tables:              Storage:                      |
  |  - samples            - dsm_tiles/                  |
  |  - pipeline_runs      - masks/                      |
  |                       - outputs/                    |
  |                                                     |
  |  Realtime:                                          |
  |  - pipeline_runs (INSERT/UPDATE broadcast)          |
  +----------------------------------------------------+
```

---

## Component Responsibilities

| Component | Responsibility | Boundary / Contract |
|-----------|----------------|---------------------|
| **panel_snap_v2** (Python, existing) | Topology-aware snapping: cluster, graph, solve, densify, validate | Input: `dict[int, ndarray]` + `dict[int, Plane]`. Output: snapped polygons + feature graph dict. No HTTP, no Pydantic imports inside the engine. |
| **FastAPI sidecar** (Python, new) | HTTP wrapper. Thin adapter -- no business logic, only I/O + task orchestration + Supabase writes | Imports pipeline functions directly (not subprocess). Pydantic validates request/response. CORS for cross-origin dashboard calls. |
| **Konva labeling canvas** (React, new) | Interactive polygon drawing/editing on DSM with shared-node magnets, undo/redo | Reads/writes mask.json via FastAPI. Calls `/snap-preview` for topology feedback. Isolated from dashboard components. |
| **Zustand + zundo store** (React, new) | Panels, vertices, shared nodes, tool mode. History tracked by zundo `temporal`. | Single source of truth for canvas state. `partialize` excludes ephemeral UI state. Serializes to mask.json on save. |
| **Dashboard pages** (Next.js, new) | Sample table, filter chips, run monitor | Server Components for initial fetch. Client Components for Realtime. Standard App Router. |
| **Supabase** (existing + new tables) | Persistent storage, auth, real-time pub-sub | New `pipeline_runs` table with Realtime. Existing `samples` table. Storage for DSMs/masks/outputs. |

---

## Recommended Project Structure

### Python Side

```
roof_pipeline/
|-- __init__.py
|-- main.py                    # Existing synthetic demo
|-- run_real.py                # Existing (has --snap-v2 flag)
|-- planes.py                  # Existing
|-- boundaries.py              # Existing
|-- snapping.py                # Existing (v1 fallback)
|-- mesh.py                    # Existing
|-- cutsheets.py               # Existing
|-- ts_export.py               # Existing
|-- ts_render_pdf.py           # Existing
|-- shop_drawings.py           # Existing
|-- label_panels.py            # Existing (CLI fallback, kept)
|
|-- panel_snap_v2/             # Milestone 1 (complete, 41 tests)
|   |-- __init__.py            # snap_polygons() public API
|   |-- winding.py             # + duplicate-corner dedup (M2 bug fix)
|   |-- clustering.py
|   |-- graph.py
|   |-- solver.py
|   |-- densify.py             # + MultiPolygon fix (M2 bug fix)
|   |-- validate.py
|   |-- schema.py              # PanelsInput Pydantic model
|   +-- diagnostics.py
|
|-- api/                       # NEW -- FastAPI sidecar
|   |-- __init__.py
|   |-- app.py                 # FastAPI app, CORS, lifespan
|   |-- routes/
|   |   |-- snap_preview.py    # POST /snap-preview (sync)
|   |   |-- pipeline.py        # POST /run-pipeline (background)
|   |   +-- labels.py          # POST/GET /labels/{sampleId}
|   |-- deps.py                # Supabase client, DSM LRU cache
|   +-- tasks.py               # Background pipeline runner
|
+-- tests/                     # Existing 41 tests + new API tests
    +-- test_api.py            # NEW -- FastAPI endpoint tests
```

### Next.js Side

```
app/
|-- labeling/
|   |-- page.tsx               # Dashboard index: sample table, filters
|   |-- [sampleId]/
|   |   +-- page.tsx           # Labeling canvas page
|   |-- components/
|   |   |-- SampleTable.tsx
|   |   |-- FilterChips.tsx
|   |   |-- RunMonitor.tsx     # Supabase Realtime subscription
|   |   +-- KonvaLoader.tsx    # dynamic import wrapper (ssr: false)
|   |-- canvas/
|   |   |-- LabelingCanvas.tsx # react-konva Stage + Layers
|   |   |-- PanelPolygon.tsx   # Single polygon with vertex handles
|   |   |-- SharedNodeMagnet.tsx  # 12px snap indicator
|   |   |-- SnapPreviewOverlay.tsx  # Valence-colored dots
|   |   +-- ToolBar.tsx
|   |-- store/
|   |   +-- useLabelingStore.ts  # Zustand + zundo temporal
|   +-- hooks/
|       |-- useSnapPreview.ts  # Debounced /snap-preview call
|       |-- useRunMonitor.ts   # Supabase Realtime subscription
|       +-- useMaskExport.ts   # Serialize store -> mask.json
```

---

## Key Architectural Patterns

### Pattern 1: Direct Function Import (No Subprocess)

The sidecar imports pipeline functions directly:

```python
from roof_pipeline.panel_snap_v2 import snap_polygons
from roof_pipeline.planes import fit_all_panels
from roof_pipeline.boundaries import polygons_from_clicks
```

Why not subprocess: 2-3s Python startup overhead, no type safety, intermediate results inaccessible. Same Python environment on the droplet makes direct import trivial.

### Pattern 2: Supabase as Pub-Sub Bridge

The sidecar does NOT manage WebSocket connections:

```
FastAPI --[INSERT/UPDATE]--> Supabase pipeline_runs table
                               |
                    Supabase Realtime (automatic broadcast)
                               |
Next.js <--[postgres_changes]-- Supabase WS channel
```

Why: Sidecar on DigitalOcean, dashboard on Vercel. WebSocket between them requires CORS, reconnection, session state. Supabase handles all of this. The sidecar just writes SQL rows.

### Pattern 3: Konva Layer Separation

Static and interactive elements live on separate Layers:

```
Stage
  Layer "background" (listening={false}, cached)
    Image (DSM hillshade)
  Layer "panels" (listening on Circle vertices only)
    Group per panel
      Line (boundary, listening={false})
      Circle (vertex handle, draggable)
  Layer "overlay" (listening={false}, snap preview only)
    Circle (valence dots)
    Line (feature edges)
```

Why: Konva maintains a hidden hit-graph canvas. Every shape with `listening={true}` participates in hit detection on every mousemove. Setting `listening={false}` on background + polygon fills eliminates this overhead. Only vertex Circles need interactivity.

### Pattern 4: zundo Partialize for Undo Granularity

```typescript
temporal(storeConfig, {
  partialize: (state) => ({
    panels: state.panels,
    sharedNodes: state.sharedNodes,
  }),
  limit: 100,
})
```

Why: Without `partialize`, every zoom, hover, and tool mode switch creates an undo entry. With drag operations at 60fps, the stack explodes. Only meaningful geometry changes enter history.

### Pattern 5: Konva SSR Guard

Konva requires browser APIs (canvas). Must use dynamic import:

```typescript
const LabelerCanvas = dynamic(
  () => import('./LabelerCanvas'),
  { ssr: false }
);
```

Plus webpack config: `config.externals = [...config.externals, { canvas: 'canvas' }]`.

---

## Anti-Patterns to Avoid

| Anti-Pattern | What Goes Wrong | Do This Instead |
|-------------|----------------|-----------------|
| Subprocess shelling to run_real.py | 2-3s startup, no type safety, no intermediate results | Direct function imports |
| WebSocket server in FastAPI for monitoring | Connection management, CORS, reconnection -- all handled by Supabase | Write status rows to Supabase, subscribe via Realtime |
| Full state snapshots for undo | Drag at 60fps = thousands of snapshots, "undo one pixel" | zundo `partialize` + `handleSet` for drag boundaries |
| Business logic in API routes | Engine must work from CLI and API. Logic in routes locks out CLI. | All geometry in `panel_snap_v2/`. Routes are thin adapters. |
| Shared mutable state between canvas and dashboard | Canvas zoom triggers dashboard re-renders. Dashboard filter triggers canvas redraws. | Separate Zustand stores. Communicate through Supabase data layer. |
| Storing panels as normalized relational data | Pipeline expects `mask.json` as a single document. Normalization creates impedance mismatch. | Store as JSONB in samples table. |

---

## Data Flow

### Snap Preview (Sync, <500ms)

```
Next.js                    FastAPI                    panel_snap_v2
  |                          |                            |
  | POST /snap-preview       |                            |
  | { panels, res_m, tol }   |                            |
  | -----------------------> |                            |
  |                          | Load DSM (LRU cached)      |
  |                          | polygons_from_clicks()     |
  |                          | fit_all_panels()           |
  |                          | --------------------------> |
  |                          | snap_polygons()            |
  |                          | <-------------------------- |
  |                          | { features, warnings }     |
  | <----------------------- |                            |
  | Render overlay           |                            |
```

### Full Pipeline Run (Async)

```
Next.js -> POST /run-pipeline -> FastAPI returns 202 immediately
                                   |
                           BackgroundTasks runs pipeline
                                   |
                           Writes status to pipeline_runs
                                   |
                           Supabase Realtime broadcasts
                                   |
                           Next.js RunMonitor receives update
```

### mask.json Contract

```json
{
  "version": 2,
  "dsm_key": "dsm_tiles/abc123.tif",
  "res_m": 0.1,
  "shape": [200, 300],
  "panels": [
    {
      "id": 1,
      "corners_pix": [[120.5, 45.2], [180.3, 45.0], [180.1, 95.8]],
      "shared_nodes": {
        "0": { "partner_panel": 2, "partner_vertex": 3 }
      }
    }
  ]
}
```

V2 additions: `version`, `shared_nodes` (magnet snap records), `dsm_key`. Pydantic on server, Zod on client.

---

## Supabase Schema

### pipeline_runs Table

```sql
CREATE TABLE pipeline_runs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  sample_id TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  stage TEXT,
  progress INTEGER DEFAULT 0,
  error TEXT,
  snap_v2_features JSONB,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

ALTER PUBLICATION supabase_realtime ADD TABLE pipeline_runs;
```

### Realtime Subscription

```typescript
supabase
  .channel(`run-${sampleId}`)
  .on('postgres_changes', {
    event: '*',
    schema: 'public',
    table: 'pipeline_runs',
    filter: `sample_id=eq.${sampleId}`,
  }, (payload) => updateRunStatus(payload.new))
  .subscribe();
```

---

## Integration Points

| Boundary | Communication | Contract |
|----------|---------------|----------|
| Dashboard -> FastAPI | HTTP POST (JSON) | Pydantic request/response. Zod mirror on client. |
| FastAPI -> panel_snap_v2 | Direct Python function call | `snap_polygons(polygons, planes, tol)` |
| FastAPI -> Supabase | supabase-py client | Service role key for status writes. |
| panel_snap_v2 -> pipeline | `dict[int, ndarray]` return | Same as `snapping.py` output. Zero downstream change. |
| Dashboard -> Supabase | @supabase/supabase-js | Generated types via `supabase gen types typescript`. |

---

## Scaling

| Scale | Approach |
|-------|----------|
| 1-50 samples/day | Single uvicorn worker. DSMs in LRU cache. Sequential runs. |
| 50-500 | Celery + Redis job queue. FastAPI returns immediately, worker runs pipeline. |
| 500+ | Not anticipated. Horizontal workers, S3 for DSMs. |

First bottleneck: DSM I/O (200-500ms per load). LRU cache with 10 entries solves for snap-preview.
Second bottleneck: `polygons_from_clicks` + `fit_all_panels` preprocessing (~200ms), not the engine (~20ms).

---

## Sources

- [FastAPI BackgroundTasks](https://fastapi.tiangolo.com/tutorial/background-tasks/) -- Context7 verified
- [FastAPI CORS](https://fastapi.tiangolo.com/tutorial/cors/) -- Context7 verified
- [Supabase Realtime postgres_changes](https://supabase.com/docs/guides/realtime/subscribing-to-database-changes) -- Context7 verified
- [Konva Layer Management](https://konvajs.org/docs/performance/Layer_Management.html) -- Context7 verified
- [Konva Objects Snapping](https://konvajs.org/docs/sandbox/Objects_Snapping.html) -- Context7 verified
- [zundo temporal middleware](https://github.com/charkour/zundo) -- Context7 verified
- [supabase-py](https://github.com/supabase/supabase-py) -- Official Python client
- [react-konva Next.js SSR](https://github.com/konvajs/react-konva/issues/787) -- dynamic import required

---
*Architecture research for Milestone 2: 2026-04-19*
