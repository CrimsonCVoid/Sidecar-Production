# Technology Stack -- Milestone 2

**Project:** FastAPI Sidecar + Labeling Dashboard (Milestone 2 of 2)
**Researched:** 2026-04-18
**Updated:** 2026-04-19 (Milestone 2 focus -- Milestone 1 complete, 41 tests passing)

## Context

Milestone 1 delivered the `panel_snap_v2` topology-aware snap engine with union-find clustering, feature graph, apex solver, densify, and validate -- all integrated behind `--snap-v2` in `run_real.py`. The engine uses only existing Python deps (scipy, numpy, shapely). Pydantic was added for input validation at the `polygons_from_clicks` boundary.

This document covers ONLY the stack additions needed for Milestone 2: the FastAPI sidecar, the Next.js Konva labeling dashboard, and the Supabase Realtime run monitor. Nothing from Milestone 1's validated stack is repeated here.

---

## Python Backend -- FastAPI Sidecar

### Core Dependencies

| Technology | Version | Purpose | Rationale | Confidence |
|------------|---------|---------|-----------|------------|
| FastAPI | >=0.115,<1.0 | HTTP endpoint for snap-preview, run-pipeline, diff | Async, auto-OpenAPI, native Pydantic v2 validation. Python 3.10+ required since 0.130.0 -- project uses 3.11, fully compatible. Current stable: 0.136.0 (released 2026-04-16). Pin >=0.115 to stay below the 0.130 Python-version bump while accepting bugfixes. | HIGH |
| uvicorn | >=0.30,<1.0 | ASGI server | Standard FastAPI server. Run as `uvicorn roof_pipeline.api.app:app --host 0.0.0.0 --port 8000`. Current stable: 0.44.0. Pin >=0.30 for stability. Included in `fastapi[standard]` extras but pin explicitly for clarity. | HIGH |
| Pydantic | >=2.0,<3.0 | Request/response validation | Already in `requirements.txt` from Milestone 1 (added for `polygons_from_clicks` boundary). FastAPI 0.115+ requires Pydantic v2. Reuse the existing `MaskContract` schema for the `/snap-preview` request body. No version change needed. | HIGH |
| supabase | >=2.0,<3.0 | Pipeline status writes to Supabase | FastAPI sidecar writes pipeline_runs status rows (`INSERT`/`UPDATE`) so the dashboard's Realtime subscription picks them up. The `supabase` Python client (supabase-py) provides `client.table("pipeline_runs").insert(...)` and `.update(...).eq("id", run_id)` for async writes. Current stable: 2.28.3 (released 2026-03-20). Uses `postgrest-py` under the hood. Do NOT use raw `psycopg2` -- the Supabase client handles auth, RLS, and connection pooling. | HIGH |
| python-multipart | >=0.0.18 | Form/file upload parsing | Transitive FastAPI dependency required for `UploadFile` and `Form` parameters. Not needed if all endpoints accept JSON bodies only (which is the current plan). Installed automatically with `pip install fastapi` but listed here for awareness. Upgraded to >=0.0.18 to fix CVE-2024-56406 (DoS via many small multipart fields). Current: 0.0.26. | MEDIUM |
| httpx | >=0.27,<1.0 | FastAPI test client | FastAPI's `TestClient` is built on httpx. Required for `pytest` testing of API routes. Not a runtime dependency -- dev/test only. Current stable: 0.28.1. | HIGH |

### What NOT to add to the sidecar

| Technology | Why Not |
|------------|---------|
| `celery` / `redis` | Overkill for current scale (1-50 samples/day). FastAPI's built-in `BackgroundTasks` handles the pipeline run in-process. Add Celery only if concurrent pipeline runs are needed later. |
| `psycopg2` / `asyncpg` | Direct Postgres connections bypass Supabase's auth and RLS. Use the `supabase` Python client instead. |
| `aiofiles` | DSM files are loaded via `rasterio.open()` which is synchronous. Wrapping in async adds complexity for no benefit -- the snap-preview endpoint should use `functools.lru_cache` on DSM loading instead. |
| `gunicorn` | uvicorn alone handles the expected load. Gunicorn + uvicorn workers is needed at scale but adds deployment complexity now. Single uvicorn process with 2 workers (`--workers 2`) is sufficient. |
| `WebSocket` server in FastAPI | The sidecar does NOT manage WebSocket connections. Pipeline progress goes through Supabase table writes -> Supabase Realtime -> dashboard. This is the key architectural decision: Supabase is the pub-sub bridge. |

### FastAPI-Specific Patterns

**CORS middleware** -- Required because the Next.js dashboard (Vercel or localhost:3000) calls the FastAPI sidecar (DigitalOcean droplet:8000). Configure in `app.py`:

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Roof Pipeline API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://mymetalroofer.com", "http://localhost:3000"],
    allow_methods=["POST"],
    allow_headers=["*"],
)
```

**BackgroundTasks** -- The `/run-pipeline` endpoint must return immediately (HTTP 202 Accepted) and run the pipeline in the background. FastAPI's `BackgroundTasks` handles this without Celery:

```python
from fastapi import BackgroundTasks

@router.post("/run-pipeline", status_code=202)
async def run_pipeline(req: RunPipelineRequest, bg: BackgroundTasks):
    bg.add_task(execute_pipeline, req.sample_id, req.snap_tol)
    return {"status": "accepted", "sample_id": req.sample_id}
```

**Sync endpoints** -- The `/snap-preview` endpoint runs synchronously (<500ms target). FastAPI runs `def` (non-async) route functions in a threadpool, which is fine for CPU-bound numpy/scipy operations. Do NOT make the snap engine async -- it is pure computation.

---

## Frontend -- Labeling Dashboard

The existing My Metal Roofer app is Next.js App Router + Supabase + TypeScript. These are the additions for Milestone 2.

### Core Dependencies

| Technology | Version | Purpose | Rationale | Confidence |
|------------|---------|---------|-----------|------------|
| konva | ^10.2 | 2D canvas rendering engine | Scene-graph architecture (Stage > Layer > Group > Shape) maps directly to the roof domain (Canvas > PanelLayer > Panel > Vertex). Dirty-region repainting for performance. Built-in hit detection via color-picking canvas. 1100+ npm dependents. Current: 10.2.5. Ships its own TypeScript types. | HIGH |
| react-konva | ^19.2 | React bindings for Konva | Declarative JSX: `<Stage>`, `<Layer>`, `<Line>`, `<Circle>`. Full event system (`onClick`, `onDragMove`, `onDragEnd`). Peer-depends on `konva` and `react`. Compatible with React 18 and 19. Current: 19.2.3. | HIGH |
| zustand | ^5.0 | Client state management | Minimal (~1KB), zero-boilerplate hook-based store. `const panels = useStore(s => s.panels)` with selector-based rendering prevents unnecessary Konva redraws when unrelated state changes. No Provider/Context wrappers. Current: 5.0.11. | HIGH |
| zundo | ^2.3 | Undo/redo middleware for Zustand | `temporal()` middleware wrapping the store. Exposes `undo()`, `redo()`, `clear()`, `pastStates`, `futureStates`. Under 700 bytes gzipped. Key options for this project: `partialize` (track only polygon state, exclude UI ephemeral state), `limit: 100` (cap memory), `handleSet` (disable tracking during drag operations to prevent state explosion). Current: 2.3.0. Requires Zustand v4.2+ or v5. | HIGH |

### Already in the project (verify versions)

| Technology | Expected Version | Purpose | Notes |
|------------|-----------------|---------|-------|
| @supabase/supabase-js | ^2.100 | Supabase client for Realtime, Storage, DB queries | Realtime `postgres_changes` subscription for run monitor. `supabase.channel('runs').on('postgres_changes', { event: '*', schema: 'public', table: 'pipeline_runs' }, handler).subscribe()`. Current: 2.103.2. |
| zod | >=3.22 | API boundary validation | Project constraint: "Zod at every API boundary." Validate FastAPI responses on client. Validate mask.json before POST. |
| next | (existing) | App router framework | No version change needed for Milestone 2. |
| typescript | (existing) | Type safety | No `any` per project constraints. |

### What NOT to add to the frontend

| Technology | Why Not |
|------------|---------|
| Fabric.js | Flat object model (no scene graph). Manual memory cleanup required for long-running sessions. React integration is community-maintained (`react-fabricjs`) vs Konva's official `react-konva`. SVG-based rendering under the hood is slower than Canvas for many-polygon redraws during drag-snap. Fabric's strength is image editing, not topology editing. |
| Pixi.js | WebGL renderer. Overkill for 2D polygon editing with ~20-50 shapes. WebGL context management adds complexity. No React wrapper at Konva's maturity level. |
| Raw Canvas 2D / SVG | No hit detection, no scene graph, no event system. SVG creates one DOM node per vertex -- 200-400 DOM nodes at 50 panels causes hit-test overhead on every mousemove. Konva does hit detection via a hidden color-picking canvas in O(1). |
| Redux / Redux Toolkit | 3-5x more boilerplate than Zustand. `createSlice` + `configureStore` + `Provider` vs Zustand's single `create()`. No benefit for single-page labeling with one store. |
| Jotai | Atom-per-vertex model fragments polygon state, making undo across multiple panels harder than Zustand's single-store snapshot. |
| Valtio | Proxy-based mutations on geometry arrays cause subtle bugs (array identity changes not detected by Konva's shallow comparison). |
| Socket.io | Adds a second real-time transport alongside Supabase Realtime. Supabase already handles pub-sub via Postgres Changes. No reason to run a separate WebSocket server. |
| @types/konva | Konva 10.x ships its own TypeScript declarations. No DefinitelyTyped package needed. |

---

## Integration Architecture

### Supabase Realtime for Pipeline Monitoring

The run monitor is the only feature that requires Supabase Realtime configuration beyond what the existing app already uses.

**Required Supabase setup:**

```sql
-- New table for pipeline run status
CREATE TABLE pipeline_runs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  sample_id TEXT NOT NULL REFERENCES samples(id),
  status TEXT NOT NULL DEFAULT 'pending',  -- pending, running, completed, failed
  stage TEXT,                               -- planes, snap_v2, mesh, cutsheets, etc.
  progress INTEGER DEFAULT 0,              -- 0-100
  error TEXT,
  snap_v2_features JSONB,                  -- feature graph JSON stored on completion
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

-- Enable Realtime on this table
ALTER PUBLICATION supabase_realtime ADD TABLE pipeline_runs;

-- RLS policy: authenticated users can read their own runs
ALTER TABLE pipeline_runs ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users can view own runs" ON pipeline_runs
  FOR SELECT USING (auth.uid() IS NOT NULL);
```

**Dashboard subscription pattern:**

```typescript
const channel = supabase
  .channel(`run-${sampleId}`)
  .on(
    'postgres_changes',
    {
      event: '*',
      schema: 'public',
      table: 'pipeline_runs',
      filter: `sample_id=eq.${sampleId}`,
    },
    (payload) => {
      updateRunStatus(payload.new as PipelineRun);
    }
  )
  .subscribe();

// Cleanup on unmount
return () => { supabase.removeChannel(channel); };
```

**Sidecar writes** (Python, supabase-py):

```python
from supabase import create_client

supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

# In background task
supabase.table("pipeline_runs").insert({
    "sample_id": sample_id,
    "status": "running",
    "stage": "planes",
    "progress": 0,
}).execute()

# Update as pipeline progresses
supabase.table("pipeline_runs").update({
    "stage": "snap_v2",
    "progress": 25,
}).eq("id", run_id).execute()
```

### Konva Layer Architecture

Critical to design upfront (see PITFALLS.md Pitfall 9 -- Konva performance):

```
Stage (container div fills viewport)
  Layer "background" (listening={false})
    Image (DSM hillshade raster)
  Layer "panels" (listening on vertex circles only)
    Group "panel-{id}" (per panel)
      Line (polygon boundary, closed=true, fill with alpha)
      Circle (vertex-0, draggable, 6px radius)
      Circle (vertex-1, draggable, 6px radius)
      ...
  Layer "overlay" (listening={false}, only during snap-preview)
    Circle (feature dot, fill by valence color)
    Line (feature edge)
    Text (magnet label "-> P3.C1")
```

Separate layers prevent the static DSM image from redrawing when vertices move. The overlay layer renders only when snap preview is active.

### Zustand + zundo Store Shape

```typescript
interface LabelingState {
  // --- Geometry (tracked by zundo) ---
  panels: Record<string, {
    id: string;
    vertices: [number, number][];  // pixel coords
    closed: boolean;
  }>;
  sharedNodes: Record<string, string[]>;  // nodeId -> ["panelId.vertexIdx", ...]

  // --- UI ephemeral (excluded from undo via partialize) ---
  activePanelId: string | null;
  hoveredVertexKey: string | null;  // "panelId.vertexIdx"
  zoom: number;
  offset: { x: number; y: number };
  toolMode: 'draw' | 'edit' | 'preview';
  snapPreview: SnapPreviewResult | null;
  magnetTarget: { panelId: string; vertexIdx: number } | null;
}

const useLabelingStore = create<LabelingState>()(
  temporal(
    (set) => ({
      panels: {},
      sharedNodes: {},
      activePanelId: null,
      hoveredVertexKey: null,
      zoom: 1,
      offset: { x: 0, y: 0 },
      toolMode: 'draw',
      snapPreview: null,
      magnetTarget: null,
    }),
    {
      partialize: (state) => ({
        panels: state.panels,
        sharedNodes: state.sharedNodes,
      }),
      limit: 100,
    }
  )
);
```

The `partialize` option is the key design choice: only `panels` and `sharedNodes` enter the undo history. Zoom, tool mode, hover state, and snap preview are ephemeral and excluded. This prevents Pitfall 8 (undo state explosion from drag operations and hover events).

---

## Shared-Node Magnet Implementation Notes

The 12px snap radius magnet is the single most important UX feature in Milestone 2. Implementation requires coordination between Konva events and Zustand state.

**Client-side proximity detection** (on every mousemove during vertex placement):

```typescript
function findMagnetTarget(
  cursorPos: { x: number; y: number },
  panels: Record<string, Panel>,
  currentPanelId: string,
  snapRadiusPx: number = 12,
): MagnetTarget | null {
  let closest: MagnetTarget | null = null;
  let minDist = snapRadiusPx;

  for (const [panelId, panel] of Object.entries(panels)) {
    if (panelId === currentPanelId) continue;  // Don't snap to own vertices
    for (let i = 0; i < panel.vertices.length; i++) {
      const [vx, vy] = panel.vertices[i];
      const dist = Math.hypot(cursorPos.x - vx, cursorPos.y - vy);
      if (dist < minDist) {
        minDist = dist;
        closest = { panelId, vertexIdx: i, position: [vx, vy] };
      }
    }
  }
  return closest;
}
```

For ~20 panels with ~8 vertices each, this is 160 distance calculations per mousemove -- trivially fast. No spatial index needed on the client.

**Shift-click override:** When shift is held, bypass magnet detection entirely and place vertex at raw cursor position. Essential for cases where the user intentionally does NOT want to snap.

---

## Version Pin Summary

### Python (`requirements.txt` additions for sidecar)

```
# API sidecar (add to requirements.txt or separate api-requirements.txt)
fastapi>=0.115,<1.0
uvicorn>=0.30,<1.0
supabase>=2.0,<3.0

# Dev/test only
httpx>=0.27,<1.0
pytest>=8.0,<10.0
pytest-cov>=5.0,<6.0
```

**Already present** (no changes needed):

```
# From Milestone 1 -- already in requirements.txt
numpy>=1.26
scipy>=1.11
shapely>=2.0
pydantic>=2.0
pytest>=7.0    # Consider bumping to >=8.0 for consistency
```

### Frontend (`package.json` additions)

```bash
# New dependencies
npm install konva@^10.2 react-konva@^19.2 zustand@^5.0 zundo@^2.3

# Already in project (verify)
# @supabase/supabase-js@^2.100
# zod@^3.22
```

### Deployment (DigitalOcean droplet)

```bash
# Install API deps on the droplet
pip install 'fastapi>=0.115' 'uvicorn>=0.30' 'supabase>=2.0'

# Run the sidecar
uvicorn roof_pipeline.api.app:app --host 0.0.0.0 --port 8000 --workers 2
```

Behind NGINX reverse proxy for HTTPS termination and CORS headers.

---

## Confidence Assessment

| Component | Confidence | Rationale |
|-----------|------------|-----------|
| FastAPI + uvicorn | HIGH | Context7-verified docs. FastAPI 0.136.0 supports Python 3.11. Standard ASGI pattern. |
| Pydantic v2 | HIGH | Already validated in Milestone 1. Reusing existing schemas. |
| supabase-py | HIGH | Official Supabase client. Stable v2.28.3. Standard insert/update pattern. |
| Konva 10.x | HIGH | Context7-verified. Scene graph architecture confirmed. React bindings official. |
| react-konva 19.x | HIGH | Context7-verified. Declarative Stage/Layer/Shape. React 18/19 compatible. |
| Zustand 5.x | HIGH | Context7-verified. Hook-based, selector-based renders. |
| zundo 2.x | HIGH | Context7-verified. temporal middleware with partialize, limit, handleSet. |
| Supabase Realtime | HIGH | Context7-verified. postgres_changes subscription with filter syntax. |
| Magnet snap (12px) | MEDIUM | Implementation pattern is sound but Konva-specific API surface (drag constraints, visual indicator rendering during mousemove) needs validation during Phase 3 planning. |

---

## Sources

### Context7 Verified (HIGH confidence)
- [FastAPI -- BackgroundTasks, response models, CORS](https://github.com/fastapi/fastapi) -- Context7 `/fastapi/fastapi`, version 0.115+
- [react-konva -- Stage, Layer, Line, Circle, event handling](https://github.com/konvajs/react-konva) -- Context7 `/konvajs/react-konva`
- [Konva -- polygon (Line closed=true), drag-snap, Objects_Snapping](https://konvajs.org/) -- Context7 `/konvajs/site`
- [Zustand -- temporal middleware ecosystem, third-party libs](https://zustand.docs.pmnd.rs/) -- Context7 `/websites/zustand_pmnd_rs`
- [zundo -- temporal(), undo/redo/clear, partialize, limit, handleSet, wrapTemporal](https://github.com/charkour/zundo) -- Context7 `/charkour/zundo`
- [Supabase Realtime -- postgres_changes, channel subscribe, filter](https://github.com/supabase/realtime) -- Context7 `/supabase/realtime`

### PyPI / npm Verified (HIGH confidence)
- [FastAPI 0.136.0](https://pypi.org/project/fastapi/) -- Released 2026-04-16. Python >=3.10.
- [uvicorn 0.44.0](https://pypi.org/project/uvicorn/) -- Released 2026-04-06.
- [supabase 2.28.3](https://pypi.org/project/supabase/) -- Released 2026-03-20. Python >=3.9.
- [python-multipart 0.0.26](https://pypi.org/project/python-multipart/) -- Released 2026-04-10. CVE fix in 0.0.18+.
- [httpx 0.28.1](https://pypi.org/project/httpx/) -- Released 2024-12-06. Stable.
- [konva 10.2.5](https://www.npmjs.com/package/konva) -- Published April 2026.
- [react-konva 19.2.3](https://www.npmjs.com/package/react-konva) -- Published February 2026.
- [zustand 5.0.11](https://www.npmjs.com/package/zustand) -- Published January 2026.
- [zundo 2.3.0](https://www.npmjs.com/package/zundo) -- 700 bytes, 231K monthly downloads.
- [@supabase/supabase-js 2.103.2](https://www.npmjs.com/package/@supabase/supabase-js) -- Published April 2026.

---
*Stack research for Milestone 2: 2026-04-19*
