# Architecture Research

**Domain:** Topology-aware roof snapping engine + web labeling dashboard
**Researched:** 2026-04-18
**Confidence:** HIGH (existing codebase fully examined; patterns grounded in prior art and verified library docs)

## Standard Architecture

### System Overview

```
                        NEXT.JS APP (My Metal Roofer)
                        ===========================
  /labeling/[sampleId]            /labeling (index)
  ┌────────────────────┐   ┌─────────────────────────────────┐
  │  Konva Canvas      │   │  Sample Table + Filter Chips     │
  │  ┌──────────────┐  │   │  Feature Graph Expand             │
  │  │ DSM Image    │  │   │  PDF Preview                      │
  │  │ + Polygons   │  │   │  Diff Viewer                      │
  │  │ + Magnets    │  │   │  Run Monitor (Supabase Realtime)  │
  │  └──────┬───────┘  │   └──────────┬──────────────────────┘
  │  Zustand Store      │              │
  │  (panels, history,  │              │
  │   snap preview)     │              │ Supabase Realtime
  └──────┬──────────────┘              │ (pipeline_runs changes)
         │                             │
         │ POST /snap-preview          │
         │ POST /run-pipeline          │
         ▼                             ▼
  ┌──────────────────────────────────────────────────────┐
  │              FASTAPI SIDECAR (DigitalOcean)          │
  │                                                      │
  │  ┌────────────┐  ┌──────────────┐  ┌──────────────┐  │
  │  │ /snap-     │  │ /run-        │  │ /diff        │  │
  │  │  preview   │  │  pipeline    │  │              │  │
  │  │ (sync,     │  │ (background  │  │ (sync)       │  │
  │  │  <500ms)   │  │  task)       │  │              │  │
  │  └─────┬──────┘  └──────┬───────┘  └──────┬───────┘  │
  │        │                │                  │          │
  │        ▼                ▼                  ▼          │
  │  ┌──────────────────────────────────────────────┐    │
  │  │          panel_snap_v2 MODULE                 │    │
  │  │                                               │    │
  │  │  ┌───────────┐  ┌──────────┐  ┌───────────┐  │    │
  │  │  │ Union-Find│→ │ Feature  │→ │ Apex      │  │    │
  │  │  │ Clustering│  │ Graph    │  │ Solver    │  │    │
  │  │  └───────────┘  └──────────┘  └───────────┘  │    │
  │  │        │              │             │         │    │
  │  │        ▼              ▼             ▼         │    │
  │  │  ┌───────────┐  ┌──────────┐  ┌───────────┐  │    │
  │  │  │ Winding   │→ │ Edge     │→ │ Shapely   │  │    │
  │  │  │ Normalizer│  │ Densifier│  │ Validator │  │    │
  │  │  └───────────┘  └──────────┘  └───────────┘  │    │
  │  └──────────────────────────────────────────────┘    │
  │                                                      │
  │  ┌──────────────────────────────────────────────┐    │
  │  │     EXISTING PIPELINE (run_real.py)           │    │
  │  │     planes.py -> boundaries.py -> mesh.py     │    │
  │  │     -> cutsheets.py / shop_drawings.py        │    │
  │  └──────────────────────────────────────────────┘    │
  └──────────────────────────┬───────────────────────────┘
                             │
                             │ Writes status rows
                             ▼
  ┌──────────────────────────────────────────────────────┐
  │                  SUPABASE                            │
  │                                                      │
  │  Tables:                  Storage:                   │
  │  - pipeline_runs          - dsm_tiles/               │
  │  - samples                - masks/                   │
  │  - snap_features          - outputs/                 │
  │                                                      │
  │  Realtime:                                           │
  │  - pipeline_runs (INSERT/UPDATE broadcast)           │
  └──────────────────────────────────────────────────────┘
```

### Component Responsibilities

| Component | Responsibility | Boundary / Contract |
|-----------|----------------|---------------------|
| **panel_snap_v2** (Python module) | Topology-aware snapping: cluster vertices, build feature graph, solve apices, densify edges, validate polygons | Input: `dict[int, np.ndarray]` polygons + `dict[int, Plane]` planes. Output: snapped polygons + `snap_v2_features.json` |
| **FastAPI sidecar** (Python service) | HTTP wrapper around Python pipeline for dashboard; snap preview, pipeline runs, diff | Thin adapter -- no business logic, only I/O + task orchestration + Supabase status writes |
| **Konva labeling canvas** (React component) | Interactive polygon drawing/editing on DSM image with shared-node magnets, undo/redo | Reads mask.json / panels.json; writes back to Supabase Storage; calls FastAPI for snap preview |
| **Zustand store** (client state) | Panels, vertices, history stack, snap preview overlay, active tool mode | Single source of truth for canvas state; serializes to mask.json on save |
| **Labeling dashboard** (Next.js pages) | Sample table, filter/status chips, run monitor, diff viewer, feature graph expand | Reads Supabase tables; subscribes to Realtime for pipeline_runs changes |
| **Supabase** (data layer) | Persistent storage for samples, pipeline run status, feature graph snapshots, file storage for DSMs/masks/outputs | Tables with RLS; Realtime publication on pipeline_runs |
| **Existing pipeline** (Python modules) | All current stages: planes -> boundaries -> snapping(v1) -> mesh -> cutsheets -> shop_drawings | Unchanged; panel_snap_v2 slots in as alternative to snapping.py via `--snap-v2` flag |

## Recommended Project Structure

### Python Side (panel_snap_v2 + FastAPI)

```
roof_pipeline/
├── __init__.py
├── main.py                    # Existing synthetic demo
├── run_real.py                # Existing real-data driver (gets --snap-v2 flag)
├── planes.py                  # Existing
├── boundaries.py              # Existing
├── snapping.py                # Existing (kept as v1 fallback)
├── mesh.py                    # Existing
├── cutsheets.py               # Existing
├── ts_export.py               # Existing
├── ts_render_pdf.py           # Existing
├── shop_drawings.py           # Existing
├── label_panels.py            # Existing (CLI fallback)
│
├── panel_snap_v2/             # NEW -- topology-aware snap engine
│   ├── __init__.py            # Public API: snap_topology_aware(polygons, planes, tol) -> SnapResult
│   ├── types.py               # SnapResult, FeatureNode, FeatureEdge, ClusterInfo dataclasses
│   ├── clustering.py          # Union-find with multi-pass expanding tolerance
│   ├── feature_graph.py       # Build adjacency graph from clusters; valence computation
│   ├── apex_solver.py         # Least-squares multi-plane intersection for valence-3+
│   ├── winding.py             # Non-convex winding normalization (Shoelace + robust fallback)
│   ├── densify.py             # Edge-walking shared-edge densification
│   ├── validate.py            # Shapely polygon validation + buffer(0) repair
│   └── export.py              # snap_v2_features.json serializer
│
├── schemas/                   # NEW -- Pydantic models at API boundaries
│   ├── __init__.py
│   ├── mask_contract.py       # MaskJson schema (what the dashboard writes)
│   └── snap_features.py       # SnapV2Features schema (feature graph output)
│
└── api/                       # NEW -- FastAPI sidecar
    ├── __init__.py
    ├── app.py                 # FastAPI app factory, CORS, lifespan
    ├── routes/
    │   ├── __init__.py
    │   ├── snap_preview.py    # POST /snap-preview (sync, <500ms target)
    │   ├── pipeline.py        # POST /run-pipeline (background task)
    │   └── diff.py            # POST /diff (compare two snap results)
    ├── deps.py                # Supabase client, shared dependencies
    └── tasks.py               # Background pipeline runner with status updates
```

### Next.js Side (Dashboard + Labeler)

```
app/
├── labeling/
│   ├── page.tsx               # Dashboard index: sample table, filters, run monitor
│   ├── [sampleId]/
│   │   └── page.tsx           # Labeling canvas for one sample
│   ├── components/
│   │   ├── SampleTable.tsx        # Sortable/filterable sample list
│   │   ├── FilterChips.tsx        # Status filter (needs-labeling, v2-verified, etc.)
│   │   ├── RunMonitor.tsx         # Supabase Realtime subscription for pipeline_runs
│   │   ├── DiffViewer.tsx         # Side-by-side snap comparison
│   │   ├── FeatureGraphPanel.tsx  # Expandable feature graph visualization
│   │   └── PdfPreview.tsx         # Embedded PDF preview iframe
│   ├── canvas/
│   │   ├── LabelingCanvas.tsx     # react-konva Stage + Layers wrapper
│   │   ├── PanelPolygon.tsx       # Single polygon with vertex handles
│   │   ├── SharedNodeMagnet.tsx   # 12px snap-radius magnet indicator
│   │   ├── SnapPreviewOverlay.tsx # Feature graph + valence dots overlay
│   │   └── ToolBar.tsx            # Tool selection (draw, edit, snap-preview)
│   ├── store/
│   │   ├── useLabelingStore.ts    # Zustand store: panels, vertices, tool mode
│   │   └── useHistoryStore.ts     # Undo/redo history stack (command pattern)
│   └── hooks/
│       ├── useSnapPreview.ts      # Debounced snap-preview API call
│       ├── useSupabaseRealtime.ts # Generic Realtime subscription hook
│       └── useMaskExport.ts       # Serialize Zustand state -> mask.json
```

### Structure Rationale

- **`panel_snap_v2/` as subpackage:** Isolates the new engine completely from the existing `snapping.py`. The `--snap-v2` flag in `run_real.py` imports from `panel_snap_v2` only when active, so the old path is fully preserved. Each file in the subpackage maps to one algorithmic stage, making the composition explicit and independently testable.

- **`schemas/` separate from `panel_snap_v2/`:** The Pydantic models serve both the Python pipeline (validation at `polygons_from_clicks` boundary) and the FastAPI sidecar (request/response validation). Keeping them outside `panel_snap_v2/` avoids coupling the pure-geometry engine to Pydantic.

- **`api/` as sibling to the pipeline:** The FastAPI sidecar lives inside `roof_pipeline/` so it can import pipeline modules directly without package installation. It is thin glue -- the heavy logic stays in `panel_snap_v2/` and existing modules.

- **Canvas components split from dashboard components:** The Konva-based labeling canvas (`canvas/`) is a self-contained rendering system with its own state management. The dashboard components (`components/`) are standard Next.js server/client components consuming Supabase data. These two groups have no shared state except through the Supabase data layer.

- **Separate history store:** Undo/redo is a cross-cutting concern distinct from the panel data model. A dedicated `useHistoryStore` implementing the command pattern avoids polluting the main labeling store with history stack logic.

## Architectural Patterns

### Pattern 1: Multi-Pass Expanding Tolerance Clustering

**What:** The union-find vertex clustering runs three passes with increasing tolerance (0.3t, 0.6t, t) instead of a single pass at the final tolerance. Each pass only merges vertices that were already members of a cluster from a prior pass OR are within that pass's tighter tolerance.

**When to use:** When transitive grouping matters -- three vertices A, B, C where dist(A,B) < 0.3t, dist(B,C) < 0.3t, but dist(A,C) = 0.5t. A single pass at 0.3t finds {A,B} and {B,C} but not the transitive group. The first pass catches tight pairs, the second extends through intermediaries, the third catches the remaining.

**Trade-offs:** Three passes of O(N^2) pairwise comparison vs one pass. For typical residential roofs (50-100 vertices), this is trivially fast. The benefit is correct hip apex grouping where no single vertex pair is within the tight tolerance but the transitive chain connects them.

**Implementation sketch:**

```python
def cluster_vertices(
    items: list[VertexRef],
    base_tol: float,
    passes: tuple[float, ...] = (0.3, 0.6, 1.0),
) -> dict[int, list[int]]:
    """Multi-pass union-find with expanding tolerance."""
    n = len(items)
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[rj] = ri

    for scale in passes:
        tol = base_tol * scale
        tol2 = tol * tol
        for i in range(n):
            for j in range(i + 1, n):
                d2 = _dist2_xy(items[i], items[j])
                if d2 <= tol2:
                    union(i, j)

    # Group by root
    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    return groups
```

### Pattern 2: Valence-Aware Apex Solving

**What:** After clustering, each cluster has a valence (number of distinct panels contributing vertices). Valence-2 clusters get midpoint averaging (same as current `snapping.py`). Valence-3+ clusters get least-squares plane intersection to find the geometrically correct apex point.

**When to use:** Hip apex convergences where 3+ panels meet. The current pipeline averages to a centroid that does not lie on any panel's plane, creating triangular slivers.

**Trade-offs:** `np.linalg.solve` for exactly 3 planes (closed-form 3x3), `np.linalg.lstsq` for 4+ (overdetermined). Both are O(1) per cluster since plane count is small. The computational cost is negligible; the value is geometric correctness.

**Implementation sketch:**

```python
def solve_apex(planes: list[Plane]) -> np.ndarray:
    """Least-squares intersection point of N >= 3 planes.

    Each plane: n . x = d  =>  [n1; n2; ...; nN] @ p = [d1; d2; ...; dN]
    For N=3: np.linalg.solve (exact).
    For N>3: np.linalg.lstsq (minimum residual).
    """
    A = np.stack([p.normal for p in planes])   # (N, 3)
    b = np.array([p.d for p in planes])        # (N,)
    if len(planes) == 3:
        return np.linalg.solve(A, b)
    else:
        result, _, _, _ = np.linalg.lstsq(A, b, rcond=None)
        return result
```

**Key insight from prior art (Ren et al. SGA21, Kelly & Wonka 2011):** Weight each plane's contribution by the inverse of its RMS fitting residual. Planes fit from more DSM points (larger panels) are more reliable and should dominate the apex position. This is a one-line change:

```python
weights = np.array([1.0 / max(p.rms_residual, 1e-6) for p in planes])
A_w = A * weights[:, None]
b_w = b * weights
```

### Pattern 3: Command-Pattern Undo/Redo with Zustand

**What:** Each user action (add vertex, move vertex, delete panel, snap-to-magnet) is a command object with `execute()` and `undo()` methods. The history store maintains a stack of executed commands and a redo stack.

**When to use:** Any interactive editor where undo/redo is expected. Konva's recommended approach per their docs is to snapshot full state history, but for polygon editing with potentially large vertex arrays, the command pattern is more memory-efficient.

**Trade-offs:** Command objects add complexity vs simple state snapshots. For this use case the trade-off is worth it because: (1) vertex arrays can be large, (2) we need to track which panels changed for the diff viewer, (3) each command carries semantic meaning useful for audit logs.

**Implementation sketch:**

```typescript
interface Command {
  execute(): void;
  undo(): void;
  description: string;
}

interface HistoryStore {
  past: Command[];
  future: Command[];
  execute(cmd: Command): void;
  undo(): void;
  redo(): void;
}

// Example command
class MoveVertexCommand implements Command {
  constructor(
    private panelId: number,
    private vertexIndex: number,
    private from: [number, number],
    private to: [number, number],
    private store: LabelingStore,
  ) {}
  description = "Move vertex";
  execute() { this.store.setVertex(this.panelId, this.vertexIndex, this.to); }
  undo() { this.store.setVertex(this.panelId, this.vertexIndex, this.from); }
}
```

### Pattern 4: SSE-Based Pipeline Monitoring via Supabase Realtime

**What:** The FastAPI sidecar updates a `pipeline_runs` Supabase table as the pipeline progresses through stages. The Next.js dashboard subscribes to Postgres changes on that table via Supabase Realtime. No direct WebSocket between FastAPI and Next.js.

**When to use:** When the pipeline runs on a different server than the dashboard (which it does -- DigitalOcean droplet vs Vercel/Next.js). Supabase acts as the pub-sub bridge, eliminating the need for the FastAPI sidecar to manage WebSocket connections.

**Trade-offs:** Adds Supabase write latency (~50-100ms per status update) but avoids WebSocket connection management in FastAPI. Supabase Realtime is already in the stack. The pipeline stages are seconds-long, so 100ms latency is imperceptible.

**Implementation sketch:**

```python
# FastAPI sidecar: tasks.py
async def run_pipeline_task(sample_id: str, supabase: Client):
    run_id = str(uuid4())
    await supabase.table("pipeline_runs").insert({
        "id": run_id, "sample_id": sample_id,
        "status": "running", "stage": "planes", "progress": 0
    }).execute()

    # Stage 1
    planes = fit_all_panels(dsm, mask, res_m)
    await supabase.table("pipeline_runs").update({
        "stage": "snap_v2", "progress": 25
    }).eq("id", run_id).execute()

    # Stage 2
    result = snap_topology_aware(polygons, planes, tol)
    await supabase.table("pipeline_runs").update({
        "stage": "mesh", "progress": 50
    }).eq("id", run_id).execute()
    # ... continues through stages
```

```typescript
// Next.js: RunMonitor.tsx
const channel = supabase
  .channel("pipeline-runs")
  .on(
    "postgres_changes",
    { event: "UPDATE", schema: "public", table: "pipeline_runs",
      filter: `sample_id=eq.${sampleId}` },
    (payload) => {
      setRunStatus(payload.new as PipelineRun);
    }
  )
  .subscribe();
```

## Data Flow

### Primary Data Flow: Labeling to Pipeline

```
User clicks corners in Konva canvas
    |
    v
Zustand store updates panels/vertices state
    |
    v (debounced, 300ms)
POST /snap-preview to FastAPI sidecar
    |
    v
panel_snap_v2.snap_topology_aware(polygons, planes, tol=preview_tol)
    |
    v
Returns snap_v2_features.json (feature graph + edge adjacency)
    |
    v
Konva SnapPreviewOverlay renders valence-colored dots + edge lines
    |
    v (user clicks "Run Pipeline")
POST /run-pipeline to FastAPI sidecar
    |
    v
FastAPI spawns background task:
    run_real.py --snap-v2 logic (inline, not subprocess)
    |
    v
Writes status updates to Supabase pipeline_runs table
    |
    v
Supabase Realtime broadcasts to RunMonitor.tsx
    |
    v
On completion: outputs stored in Supabase Storage
    Dashboard shows "v2-verified / clean" badge
```

### Snap Preview Data Flow (Synchronous, <500ms)

```
Next.js                   FastAPI                      panel_snap_v2
  |                         |                              |
  |  POST /snap-preview     |                              |
  |  { panels: [{id, corners_pix}],                        |
  |    dsm_key, tol }       |                              |
  | ----------------------> |                              |
  |                         |  Load DSM from Supabase      |
  |                         |  Storage (cached in-memory)  |
  |                         |                              |
  |                         |  polygons_from_clicks()      |
  |                         |  fit_all_panels()            |
  |                         | ---------------------------> |
  |                         |  snap_topology_aware()       |
  |                         | <--------------------------- |
  |                         |  SnapResult {                |
  |                         |    polygons,                 |
  |                         |    features: {               |
  |                         |      nodes: [{xy, valence}], |
  |                         |      edges: [{src, dst}]     |
  |                         |    }                         |
  |                         |  }                           |
  |  200 OK                 |                              |
  |  { features, warnings } |                              |
  | <---------------------- |                              |
```

### mask.json Contract (Dashboard -> Pipeline)

This is the critical data boundary. The dashboard writes this; the pipeline consumes it via `polygons_from_clicks()`.

```json
{
  "version": 2,
  "dsm_key": "dsm_tiles/abc123.tif",
  "res_m": 0.1,
  "panels": [
    {
      "id": 1,
      "label": "P1",
      "corners_pix": [[120.5, 45.2], [180.3, 45.0], [180.1, 95.8], [120.2, 96.0]],
      "shared_nodes": {
        "0": { "partner_panel": 2, "partner_vertex": 3 },
        "1": { "partner_panel": 2, "partner_vertex": 2 }
      }
    }
  ]
}
```

Key additions over the current `panels.json` format:
- `version: 2` for schema evolution
- `shared_nodes` map: the dashboard records which vertices were snapped together via the magnet UX, giving the snap engine prior knowledge of intended adjacency
- `dsm_key` for Supabase Storage lookup

Validated by Pydantic schema at `schemas/mask_contract.py`.

### snap_v2_features.json Contract (Pipeline -> Dashboard)

```json
{
  "version": 1,
  "tol_m": 1.0,
  "clusters": [
    {
      "id": 0,
      "centroid_xy": [15.2, 8.7],
      "apex_xyz": [15.2, 8.7, 12.3],
      "valence": 3,
      "panel_ids": [1, 2, 3],
      "method": "lstsq_3plane"
    }
  ],
  "edges": [
    {
      "panel_a": 1, "panel_b": 2,
      "shared_vertices": 2,
      "type": "ridge"
    }
  ],
  "warnings": [
    { "code": "SELF_INTERSECTING", "panel_id": 4, "repaired": true }
  ]
}
```

This is what the dashboard's SnapPreviewOverlay and FeatureGraphPanel consume.

## panel_snap_v2 Internal Composition

### Stage Pipeline Within the Snap Engine

```
Input: polygons dict + planes dict + tol
                |
    ┌───────────▼───────────────┐
    │  1. WINDING NORMALIZATION │  winding.py
    │  Ensure all polygons CCW  │  Uses robust signed-area with
    │  (handles non-convex)     │  triangulation decomposition
    └───────────┬───────────────┘  for L-shapes, not just Shoelace
                │
    ┌───────────▼───────────────┐
    │  2. VERTEX CLUSTERING     │  clustering.py
    │  Union-find, 3 passes:    │  XY-distance only (like current
    │  0.3t -> 0.6t -> 1.0t     │  snap_shared_corners_xy)
    │  Groups transitive apex   │
    │  vertices                 │
    └───────────┬───────────────┘
                │
    ┌───────────▼───────────────┐
    │  3. FEATURE GRAPH BUILD   │  feature_graph.py
    │  Clusters -> nodes        │  Each node: centroid_xy, valence,
    │  Panel adjacency -> edges │  contributing panel_ids
    │  Valence = # distinct     │
    │  panels in cluster        │
    └───────────┬───────────────┘
                │
    ┌───────────▼───────────────┐
    │  4. APEX SOLVING          │  apex_solver.py
    │  Valence 2: midpoint avg  │  Same as current snapping.py
    │  Valence 3: solve(A,b)    │  Closed-form 3x3
    │  Valence 4+: lstsq(A,b)  │  Least-squares, residual-weighted
    │  Write apex XYZ back to   │
    │  each polygon's vertex    │
    └───────────┬───────────────┘
                │
    ┌───────────▼───────────────┐
    │  5. EDGE DENSIFICATION    │  densify.py
    │  Walk shared edges,       │  Same concept as current
    │  insert collinear vertices│  densify_shared_edges_xy but
    │  Uses feature graph to    │  uses adjacency from step 3
    │  know which edges to walk │  instead of brute-force search
    └───────────┬───────────────┘
                │
    ┌───────────▼───────────────┐
    │  6. SHAPELY VALIDATION    │  validate.py
    │  Check each polygon:      │  shapely.validation.make_valid()
    │  - is_valid               │  or buffer(0) for self-intersections
    │  - is_simple              │  Log warnings, auto-repair
    │  - no self-intersections  │
    └───────────┬───────────────┘
                │
    Output: SnapResult(polygons, features_json)
```

### Why This Ordering

1. **Winding before clustering:** Clustering uses vertex positions; winding normalization does not change positions, only vertex order. But the feature graph (step 3) relies on consistent winding to determine edge direction. Normalizing first prevents the feature graph from mis-identifying shared edges.

2. **Clustering before feature graph:** The feature graph is derived from cluster membership. Each cluster that spans 2+ panels creates an edge in the graph. This is the fundamental difference from the current pairwise approach -- the graph encodes N-ary relationships.

3. **Apex solving before densification:** Apex solving changes vertex positions (replacing centroids with plane intersection points). Densification inserts new vertices along edges between existing vertices. If densification ran first, the inserted vertices would be positioned relative to the old (wrong) apex positions and would need repositioning.

4. **Validation last:** The Shapely validation pass catches self-intersections introduced by aggressive apex solving or densification. It must run after all vertex modifications are complete.

## Integration With Existing Pipeline

### run_real.py Modification

The change is minimal -- a new flag and import:

```python
# In run_real.py, after polygon extraction:
if args.snap_v2:
    from .panel_snap_v2 import snap_topology_aware
    result = snap_topology_aware(polygons, planes, tol=args.snap_tol)
    polygons = result.polygons
    result.write_features(args.out_dir / "snap_v2_features.json")
else:
    # existing v1 path unchanged
    polygons = snap_shared_corners_xy(polygons, planes, tol=args.snap_tol)
    polygons = densify_shared_edges_xy(polygons, planes, tol=args.snap_tol * 0.6)
```

Everything downstream (`mesh.py`, `cutsheets.py`, `shop_drawings.py`, `ts_export.py`, `ts_render_pdf.py`) receives the same `dict[int, np.ndarray]` polygons dict regardless of which snap path ran. No changes needed in any downstream module.

### FastAPI Sidecar Integration

The sidecar does not shell out to `run_real.py`. It imports the pipeline functions directly:

```python
# api/routes/pipeline.py
from roof_pipeline.planes import fit_all_panels
from roof_pipeline.boundaries import polygons_from_clicks
from roof_pipeline.panel_snap_v2 import snap_topology_aware
from roof_pipeline.mesh import build_roof_mesh, export_mesh
from roof_pipeline.cutsheets import write_cutsheets_pdf
# ...
```

This avoids subprocess overhead and gives the sidecar direct access to intermediate results (e.g., returning the feature graph from snap_topology_aware without re-parsing JSON).

## Scaling Considerations

| Scale | Architecture Adjustments |
|-------|--------------------------|
| 1-50 samples/day (current) | Single FastAPI worker on existing DigitalOcean droplet. DSM files cached in-memory (LRU, ~50MB for 10 DSMs). Pipeline runs are sequential per request. |
| 50-500 samples/day | Add Celery + Redis for pipeline job queue. FastAPI accepts the job, returns immediately, worker picks up. Supabase Realtime for status unchanged. |
| 500+ samples/day | Not anticipated in the foreseeable future for this product. Would require horizontal scaling of pipeline workers, S3/R2 for DSM storage instead of Supabase Storage, and potentially GPU-accelerated plane fitting. |

### Scaling Priorities

1. **First bottleneck: DSM file I/O.** Loading a 10MB GeoTIFF via rasterio takes 200-500ms. The snap-preview endpoint needs sub-500ms response. Solution: LRU cache of recently loaded DSMs in the FastAPI process. A simple `functools.lru_cache` on `_load_dsm(path)` with a 10-entry limit handles this.

2. **Second bottleneck: Snap preview latency.** The full `snap_topology_aware` pipeline (6 stages) on a 10-panel roof with 50 vertices takes ~20ms. The bottleneck is the `polygons_from_clicks` + `fit_all_panels` preprocessing, not the snap engine. For preview, cache the plane fits (they change only when the DSM changes) and rerun only the snap engine stages on vertex edits.

## Anti-Patterns

### Anti-Pattern 1: Subprocess Shelling to run_real.py

**What people do:** Run `subprocess.call(["python", "-m", "roof_pipeline.run_real", ...])` from the FastAPI sidecar, passing arguments via CLI.

**Why it's wrong:** Loses type safety, adds 2-3 seconds of Python startup overhead, makes it impossible to return intermediate results (feature graph, snap warnings) without parsing stdout or temp files. Error handling becomes string parsing.

**Do this instead:** Import pipeline functions directly. The FastAPI sidecar and the pipeline share the same Python environment on the DigitalOcean droplet. Direct function calls give type-checked arguments, immediate access to return values, and Python exception handling.

### Anti-Pattern 2: WebSocket from FastAPI to Next.js for Run Monitoring

**What people do:** Open a WebSocket from the browser to the FastAPI sidecar and push pipeline progress events through it.

**Why it's wrong:** The FastAPI sidecar runs on DigitalOcean (likely behind a reverse proxy). The Next.js app may run on Vercel. WebSocket connections between these would require CORS handling, connection pooling, reconnection logic, and the sidecar would need to manage WebSocket session state. Supabase Realtime already handles all of this.

**Do this instead:** The sidecar writes status updates to a Supabase `pipeline_runs` table. The Next.js dashboard subscribes to Postgres changes on that table via Supabase Realtime. The sidecar does not need to know about connected clients at all.

### Anti-Pattern 3: Full State Snapshot for Undo/Redo

**What people do:** Clone the entire Zustand store state on every user action and push it to a history array (as Konva docs suggest).

**Why it's wrong:** For a 15-panel roof with 8 vertices each, the polygon data is 120 vertex objects. Snapshots are wasteful and make it impossible to show the diff viewer ("what changed between these two states?").

**Do this instead:** Command pattern -- each action records the minimum delta needed to undo it. Commands carry semantic meaning (MoveVertex, AddPanel, SnapToMagnet) that the diff viewer can display.

### Anti-Pattern 4: Placing Business Logic in the FastAPI Layer

**What people do:** Put snapping algorithm details, tolerance calculations, or feature graph construction logic inside FastAPI route handlers.

**Why it's wrong:** The snap engine must work both from the CLI (`run_real.py --snap-v2`) and from the API. If the logic lives in the API layer, the CLI path cannot use it without importing FastAPI.

**Do this instead:** All geometry and algorithm logic lives in `panel_snap_v2/`. The FastAPI routes are thin adapters that deserialize requests, call `panel_snap_v2` functions, and serialize responses. The CLI path calls the same functions directly.

## Integration Points

### External Services

| Service | Integration Pattern | Notes |
|---------|---------------------|-------|
| Supabase Postgres | supabase-py client in FastAPI deps; @supabase/supabase-js in Next.js | RLS policies needed for pipeline_runs table. Enable Realtime publication on pipeline_runs. |
| Supabase Storage | supabase-py for upload/download of DSMs, masks, outputs | DSMs are 5-15MB GeoTIFFs. Use signed URLs for dashboard preview. |
| Supabase Realtime | Postgres changes subscription in Next.js client | Filter on `sample_id` to avoid receiving all run updates. One channel per sample view. |
| DigitalOcean Droplet | Existing infrastructure; FastAPI runs as systemd service or docker-compose | Uvicorn with 2 workers. NGINX reverse proxy for HTTPS + CORS. |

### Internal Boundaries

| Boundary | Communication | Contract | Notes |
|----------|---------------|----------|-------|
| Dashboard -> FastAPI | HTTP POST (JSON) | Pydantic request/response models validated by Zod on client, Pydantic on server | Zod schema must mirror Pydantic model. Generate one from the other if possible. |
| FastAPI -> panel_snap_v2 | Direct Python function call | `snap_topology_aware(polygons, planes, tol) -> SnapResult` | No serialization overhead. |
| FastAPI -> Supabase | supabase-py async client | SQL inserts/updates via client library | Use service role key for status writes (not user JWT). |
| panel_snap_v2 -> existing pipeline | `dict[int, np.ndarray]` return | Same interface as `snapping.py` output | Zero change to downstream consumers. |
| Dashboard -> Supabase | @supabase/supabase-js | Typed via generated types from Supabase CLI `gen types` | Run `supabase gen types typescript` after schema changes. |

## Suggested Build Order

### Phase Dependency Graph

```
                 Winding Normalizer
                        |
              Union-Find Clustering
                        |
                Feature Graph Build
                   /          \
          Apex Solver      Edge Densifier
                   \          /
              Shapely Validator
                        |
              snap_v2 Integration
              (run_real.py --snap-v2)
                        |
                   7 Unit Tests
                        |
           ──────── PYTHON COMPLETE ────────
                        |
              Pydantic Schemas
              (mask_contract, snap_features)
                        |
           FastAPI Sidecar (snap-preview)
                        |
           Zustand Store + Konva Canvas
           (labeling, magnets, undo/redo)
                        |
           Snap Preview Integration
           (canvas calls FastAPI)
                        |
           FastAPI Pipeline Route
           + Supabase Status Writes
                        |
           Dashboard (table, monitor,
           diff, feature graph, PDF)
```

### Rationale for Ordering

1. **Snap engine first, dashboard second:** The engine is the core value. It must work standalone via CLI before any web UI exists. Testing happens at the CLI level with known roof samples.

2. **Winding before clustering:** Clustering assumes consistent vertex ordering. If winding is wrong, the feature graph will produce incorrect edge adjacency. Winding normalization has zero dependencies on other new code.

3. **Pydantic schemas before FastAPI:** The schemas define the contract between the systems. Writing them first forces explicit decisions about data shapes before writing API handlers or dashboard code.

4. **Konva canvas before dashboard:** The canvas is the primary user interaction surface. The dashboard (table, monitor, diff) is secondary chrome around it. Ship the canvas with minimal dashboard, then iterate on dashboard features.

5. **Pipeline route + monitoring last:** This depends on both the snap engine (to run) and Supabase Realtime (to broadcast status). It also depends on the dashboard existing to display the status.

## Sources

- [FastAPI SSE documentation](https://fastapi.tiangolo.com/advanced/websockets/) - Verified via Context7 (FastAPI 0.135.0+)
- [Supabase Realtime with Next.js](https://supabase.com/docs/guides/realtime/realtime-with-nextjs) - Official Supabase docs
- [Konva.js Image Labeling sandbox](https://konvajs.org/docs/sandbox/Image_Labeling.html) - Official Konva docs
- [React Konva event handling and undo/redo](https://konvajs.org/docs/react/Undo-Redo.html) - Official Konva docs
- [Ren et al. SGA21 roofOptimization](https://github.com/llorz/SGA21_roofOptimization) - "Intuitive and Efficient Roof Modeling for Reconstruction and Synthesis" (ACM TOG 2021)
- [Kelly & Wonka 2011](https://link.springer.com/chapter/10.1007/978-3-662-49247-5_2) - Constructive roof modeling with plane intersections
- [numpy.linalg.solve](https://numpy.org/doc/stable/reference/generated/numpy.linalg.solve.html) - Exact 3x3 plane intersection
- [numpy.linalg.lstsq](https://numpy.org/doc/stable/reference/generated/numpy.linalg.lstsq.html) - Overdetermined plane intersection (4+ planes)
- [CGAL Polygon Mesh Processing](https://doc.cgal.org/latest/Polygon_mesh_processing/index.html) - Mesh welding and validation patterns
- [Disjoint-set / Union-Find (Princeton)](https://algs4.cs.princeton.edu/15uf/) - Path compression + union by rank reference
- [Welding Triangles in a Mesh with tolerance](https://hamelot.io/programming/welding-triangles/) - Practical mesh welding with spatial hashing
- [Kanvas (Next.js + Konva + Zustand + Supabase)](https://github.com/Amanuel-1/kanvas) - Reference implementation for canvas editor with undo/redo
- [FastAPI WebSocket architecture at scale (2025)](https://hexshift.medium.com/how-to-incorporate-advanced-websocket-architectures-in-fastapi-for-high-performance-real-time-b48ac992f401) - Informed the decision to use Supabase Realtime instead

---
*Architecture research for: topology-aware roof snapping + web labeling dashboard*
*Researched: 2026-04-18*
