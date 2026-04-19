# Technology Stack

**Project:** Topology-Aware Snap Engine + Web Labeling Dashboard
**Researched:** 2026-04-18

## Recommended Stack

This stack adds two capabilities to the existing Python pipeline and Next.js SaaS app: (1) a topology-aware polygon snap engine with union-find clustering and multi-plane apex solving, and (2) a canvas-based labeling dashboard with shared-node magnets, undo/redo, and real-time pipeline monitoring. No existing dependencies are replaced.

---

### Python Backend -- Snap Engine (panel_snap_v2)

All additions below are zero-new-dependency. The project constraint says "No new deps in the pipeline module (shapely and scipy already present)." Every recommendation here uses numpy, scipy, or shapely -- already in `requirements.txt`.

| Technology | Version | Purpose | Why | Confidence |
|------------|---------|---------|-----|------------|
| `scipy.cluster.hierarchy.DisjointSet` | scipy >= 1.11 (already pinned) | Union-find for vertex clustering | SciPy's built-in DisjointSet uses path-halving find + merge-by-size. Zero dependencies to add. API: `ds.merge(a, b)`, `ds[x]` for find, `ds.connected(a, b)`, `ds.subsets()`. Introduced in SciPy 1.6, stable through current 1.17.x. Custom union-find would duplicate this. | HIGH |
| `numpy.linalg.lstsq` | numpy >= 1.26 (already pinned) | Least-squares multi-plane apex solving | For valence-3+ apex points where 3+ roof planes meet. Build matrix A of plane normals [n1; n2; n3; ...] and vector b of plane offsets [d1; d2; d3; ...], solve `lstsq(A, b)` for the apex point. Returns residuals for quality check. Uses LAPACK GELSD internally. For exactly 3 planes, `numpy.linalg.solve(A, b)` is a direct 3x3 solve (cheaper, exact). Use `lstsq` for valence 4+ where the system is overdetermined. | HIGH |
| `numpy.cross` | numpy >= 1.26 | 3-plane intersection closed-form | For exactly 3 planes (the common hip apex case), use the closed-form: `p = (d1*(n2 x n3) + d2*(n3 x n1) + d3*(n1 x n2)) / det([n1; n2; n3])`. Faster than lstsq, no iterative solver overhead. Fall back to lstsq at valence 4+. | HIGH |
| `shapely.validation.make_valid` | shapely >= 2.0 (already pinned) | Polygon repair after snapping | `make_valid(polygon)` fixes self-intersections, collapses, and ring ordering. Replaces the `buffer(0)` trick which can erode thin slivers. Available since Shapely 2.0. Current stable: 2.1.2. | HIGH |
| `shapely.ops.snap` | shapely >= 2.0 | Geometric vertex snapping | `snap(geom, reference, tolerance)` snaps vertices of one geometry to another within tolerance. Useful for edge-walking densification where shared edges need identical vertex sequences. | HIGH |
| `shapely.ops.unary_union` | shapely >= 2.0 | Validation of zero-gap mesh | After snapping, `unary_union(all_polygons)` should produce a single polygon with no interior gaps. If the result has interior rings, there are slivers. Diagnostic tool, not a fix. | HIGH |
| `scipy.spatial.KDTree` | scipy >= 1.11 | Spatial indexing for vertex proximity | For the 3-pass expanding tolerance (0.3t, 0.6t, t), query `KDTree.query_ball_point(vertex, radius)` to find neighbors. O(N log N) build, O(log N) per query. Already in scipy -- no new dep. Better than O(N^2) pairwise distance. | HIGH |

**NOT recommended for the snap engine:**

| Technology | Why Not |
|------------|---------|
| `scipy.optimize.least_squares` (nonlinear) | Overkill. Plane intersection is a *linear* system. `numpy.linalg.lstsq` solves it directly. Nonlinear LS adds Jacobian complexity for no benefit here. |
| `scipy.linalg.lstsq` (vs numpy) | Functionally identical for this use case. `numpy.linalg.lstsq` is already imported throughout the codebase (planes.py uses numpy SVD). Don't mix scipy and numpy linalg for the same operation. |
| NetworkX for feature graph | NetworkX 3.6 would add ~2MB of dependency for what is fundamentally a `dict[int, set[int]]` adjacency list with ~20-50 nodes. The feature graph here has at most a few dozen panels. Write a simple `FeatureGraph` dataclass with `add_edge`, `neighbors`, `degree` methods. Export to JSON directly. |
| Custom union-find implementation | SciPy's `DisjointSet` already has path-halving + merge-by-size. Writing your own is a bug magnet for the weighted/path-compressed invariants. |
| CGAL Python bindings | Massive C++ dependency, poor pip installability, overkill for 2D polygon operations that Shapely handles natively via GEOS. |

### API Sidecar (FastAPI)

| Technology | Version | Purpose | Why | Confidence |
|------------|---------|---------|-----|------------|
| FastAPI | >= 0.115 | Snap-preview HTTP endpoint | Already planned for the existing DigitalOcean droplet. Lightweight, async, auto-generates OpenAPI spec. Current stable: ~0.135.x. Pin >= 0.115 for stability. Requires Python 3.10+ after 0.130.0, but the project uses 3.11 already. | HIGH |
| Pydantic v2 | >= 2.10 | Request/response schema validation | FastAPI's native validator. Use for the `polygons_from_clicks` contract boundary, snap-preview request body, and `snap_v2_features.json` schema. Current stable: 2.13.2. Already a transitive FastAPI dep. | HIGH |
| uvicorn | >= 0.30 | ASGI server | Standard FastAPI runner. `uvicorn snap_api:app --host 0.0.0.0 --port 8000`. Already standard in the FastAPI ecosystem. | HIGH |

### Testing

| Technology | Version | Purpose | Why | Confidence |
|------------|---------|---------|-----|------------|
| pytest | >= 8.0 | Test runner for panel_snap_v2 | No test framework currently configured. pytest is the Python standard. Current stable: 9.0.3. Required for the 7 specific correctness tests specified in PROJECT.md. | HIGH |
| pytest-cov | >= 5.0 | Coverage reporting | Ensures the 7 snap tests cover the critical paths (winding normalization, apex merge, transitive cluster). | MEDIUM |

---

### Frontend -- Labeling Dashboard

The existing app is Next.js + Supabase + TypeScript. These additions integrate into that stack.

| Technology | Version | Purpose | Why | Confidence |
|------------|---------|---------|-----|------------|
| Konva | 10.x | 2D canvas rendering engine | Scene-graph architecture with automatic dirty-region repainting. Hierarchical node model (Stage > Layer > Group > Shape) maps directly to the roof domain model (Canvas > PanelLayer > Panel > Vertex). Proactive memory management for long-running labeling sessions. 1100+ downstream npm dependents. Current: 10.2.5. | HIGH |
| react-konva | 19.x | React bindings for Konva | Declarative `<Stage>`, `<Layer>`, `<Line>`, `<Circle>` JSX components. Full event system (onClick, onDragMove, onMouseEnter). Integrates with React 18/19 concurrent mode. Current: 19.2.3. | HIGH |
| Zustand | 5.x | Client state management | Minimal store (~1KB) with zero boilerplate. Hook-based: `const panels = useStore(s => s.panels)`. No providers/context wrappers needed. Selector-based renders prevent full canvas re-renders when unrelated state changes. Current: 5.0.11. | HIGH |
| zundo | 2.x | Undo/redo middleware for Zustand | `temporal()` middleware wraps the store. Exposes `undo()`, `redo()`, `clear()`, `pastStates`, `futureStates`. Under 700 bytes. `partialize` option to track only polygon state (exclude UI ephemeral state like hover, zoom). `limit: 100` caps memory. Current: 2.3.0. | HIGH |
| @supabase/supabase-js | 2.x | Realtime pipeline monitoring | Postgres Changes subscription: `supabase.channel('runs').on('postgres_changes', { event: '*', schema: 'public', table: 'pipeline_runs' }, handler).subscribe()`. Filter with `filter: 'sample_id=eq.abc'`. Broadcast for ephemeral notifications. Existing project dependency. Current: 2.103.2. | HIGH |
| Zod | >= 3.22 | API boundary validation | Already required by project constraints ("Zod at every API boundary"). Validate FastAPI responses on the client side. Validate `mask.json` shape before POST. | HIGH |

**NOT recommended for the frontend:**

| Technology | Why Not |
|------------|---------|
| Fabric.js | Flat object model requires manual memory cleanup for long-running apps. No built-in scene graph hierarchy (Stage/Layer/Group). React integration is community-maintained (`react-fabricjs`) vs Konva's official `react-konva`. Fabric uses SVG-based rendering internally which is slower for the many-polygon redraws needed during drag-snap operations. Fabric's sweet spot is image editing (filters, crops), not interactive polygon topology editing. |
| Pixi.js | WebGL-first renderer. Overkill for 2D polygon editing with ~20-50 shapes. WebGL context management adds complexity. No built-in React wrapper of Konva's maturity. Better for games/particles, not geometric annotation. |
| SVG (raw or react-svg-draw) | DOM-based rendering. Each polygon vertex is a DOM node. At 50+ panels with 4-8 vertices each = 200-400 DOM nodes being hit-tested on every mouse move for snap detection. Canvas (Konva) does this in a single composited layer with O(1) hit detection via color picking. |
| Redux / Redux Toolkit | 3-5x more boilerplate than Zustand for the same undo/redo pattern. `createSlice` + `configureStore` + `Provider` + selectors vs. Zustand's single `create()` call. No benefit for a single-page labeling tool with one store. |
| Jotai / Valtio | Both are fine state managers, but Zustand has the temporal middleware ecosystem (zundo) purpose-built for undo/redo. Jotai's atom model fragments polygon state across many atoms, making undo across multiple panels harder. Valtio's proxy model can cause subtle mutation bugs in geometry arrays. |
| Socket.io for monitoring | Adds a second real-time transport alongside Supabase Realtime. The project already has Supabase. Using Postgres Changes means the pipeline writes to a `pipeline_runs` table and the dashboard subscribes automatically -- no separate WebSocket server needed. |

---

## Detailed Rationale for Key Decisions

### Union-Find: SciPy DisjointSet vs. Custom

The PROJECT.md specifies "union-find clustering" with "3-pass expanding tolerance (0.3t, 0.6t, t)." The algorithm is:

1. Build KDTree from all polygon vertices.
2. For each tolerance in [0.3t, 0.6t, t]:
   - For each vertex, find neighbors within tolerance via `KDTree.query_ball_point`.
   - `DisjointSet.merge(v_i, v_j)` for each neighbor pair.
3. After all passes, `DisjointSet.subsets()` gives the vertex clusters.
4. For each cluster, determine valence (how many distinct panels contribute).
5. Valence 2: midpoint snap. Valence 3: closed-form triple-plane intersection. Valence 4+: lstsq.

SciPy's DisjointSet handles this directly. The `merge()` operation is amortized O(alpha(N)) with path halving. No reason to reimplement.

### Least-Squares Solver: numpy vs. scipy

For the apex solver, the system is `A @ x = b` where A is (K, 3) matrix of plane normals and b is (K,) vector of plane offsets. This is a standard linear least-squares problem.

- **Valence 3 (exact):** `numpy.linalg.solve(A, b)` -- direct solve, O(1) essentially for 3x3.
- **Valence 4+ (overdetermined):** `numpy.linalg.lstsq(A, b)` -- SVD-based, returns residuals for quality.
- **Residual check:** If `residuals[0] > threshold`, the planes don't converge cleanly -- flag for review.

Kelly & Wonka (2011) and Ren et al. (SGA21) both use this exact formulation. Their refinement is in residual weighting: weight each plane's row by `1/rms_residual` from the SVD plane fit. This is a single line: `W = np.diag(1.0 / rms_residuals); lstsq(W @ A, W @ b)`.

### Konva Canvas Architecture for Labeling

The labeling dashboard renders:
- Background: DSM hillshade raster image (one Konva `Image` node).
- Polygon layer: `<Line>` for each panel boundary (closed polygon, fillEnabled).
- Vertex layer: `<Circle>` for each corner, draggable with snap constraints.
- Overlay layer: Feature graph edges, valence dots, magnet indicators.

Konva's scene graph maps this naturally:

```
Stage
  Layer (background)
    Image (hillshade)
  Layer (panels)
    Group (panel-1)
      Line (boundary)
      Circle (vertex-0, draggable)
      Circle (vertex-1, draggable)
      ...
    Group (panel-2)
      ...
  Layer (overlay)
    Line (feature-edge-0)
    Circle (apex-dot, fill by valence)
    Text (magnet label "-> P3.C1")
```

### Zustand + zundo for Undo/Redo

The store shape for the labeling state:

```typescript
interface LabelingState {
  // Geometry (tracked by zundo)
  panels: Record<string, Panel>;      // panel ID -> vertices, plane
  sharedNodes: Record<string, string[]>; // node ID -> [panelId.vertexIdx, ...]

  // UI ephemeral (NOT tracked by zundo via partialize)
  hoveredPanel: string | null;
  selectedPanel: string | null;
  zoom: number;
  snapPreview: FeatureGraph | null;
}
```

zundo's `partialize` excludes UI state from undo history:

```typescript
const useStore = create<LabelingState>()(
  temporal(
    (set) => ({ /* ... */ }),
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

### Supabase Realtime for Pipeline Monitoring

The dashboard's run monitor subscribes to a `pipeline_runs` table:

```typescript
supabase
  .channel('run-monitor')
  .on('postgres_changes', {
    event: '*',
    schema: 'public',
    table: 'pipeline_runs',
    filter: `sample_id=eq.${sampleId}`,
  }, (payload) => {
    // payload.new has: status, stage, progress, error, snap_v2_features
    updateRunStatus(payload.new);
  })
  .subscribe();
```

The FastAPI sidecar writes to this table as the pipeline progresses:
`INSERT INTO pipeline_runs (sample_id, status, stage) VALUES (...)`

No additional WebSocket server needed. Supabase handles the pub/sub.

---

## Alternatives Considered

| Category | Recommended | Alternative | Why Not |
|----------|-------------|-------------|---------|
| Union-find | `scipy.cluster.hierarchy.DisjointSet` | Custom Python class | SciPy's is battle-tested with path halving + merge-by-size. Custom impl risks subtle bugs in rank/size tracking. |
| Spatial index | `scipy.spatial.KDTree` | `shapely.STRtree` | KDTree is better for point-radius queries (vertex proximity). STRtree is better for polygon intersection queries. Our use case is vertex clustering. |
| LS solver | `numpy.linalg.lstsq` + `numpy.linalg.solve` | `scipy.optimize.least_squares` | Plane intersection is linear, not nonlinear. scipy's NLS solver adds Jacobian overhead for zero benefit. |
| Polygon repair | `shapely.validation.make_valid` | `polygon.buffer(0)` | `buffer(0)` can erode thin slivers and change polygon area. `make_valid` preserves area while fixing topology. |
| Feature graph | Simple `dict[int, set[int]]` + dataclass | NetworkX | ~20-50 node graph does not justify a 2MB dependency. Adjacency dict + a 30-line class covers degree, neighbors, JSON export. |
| Canvas lib | Konva + react-konva | Fabric.js | Scene graph architecture, official React bindings, dirty-region rendering, automatic memory management. Fabric's flat model requires manual cleanup. |
| Canvas lib | Konva + react-konva | Raw Canvas 2D API | No hit detection, no event system, no scene graph. Would require reimplementing what Konva provides. |
| State mgmt | Zustand + zundo | Redux + redux-undo | 5x less boilerplate. zundo is 700 bytes vs redux-undo's 3KB+. Zustand's selector model prevents unnecessary Konva re-renders. |
| Realtime | Supabase Postgres Changes | Polling / SSE | Already using Supabase. Postgres Changes is push-based with row-level filtering. Polling wastes bandwidth; SSE requires a separate endpoint. |
| API framework | FastAPI | Flask | FastAPI has native async, Pydantic validation, auto-OpenAPI docs. Flask would need flask-pydantic, flask-cors, etc. as separate deps. |

---

## Version Pin Summary

### Python (requirements.txt additions)

```bash
# Snap engine -- NO new core deps (all already in requirements.txt)
# scipy >= 1.11     (DisjointSet, KDTree -- already present)
# numpy >= 1.26     (lstsq, linalg.solve -- already present)
# shapely >= 2.0    (make_valid, snap, unary_union -- already present)

# API sidecar (separate requirements or optional extras)
fastapi>=0.115,<1.0
pydantic>=2.10,<3.0
uvicorn>=0.30,<1.0

# Testing (dev dependencies)
pytest>=8.0,<10.0
pytest-cov>=5.0,<6.0
```

### Frontend (package.json additions)

```bash
# Canvas + state
npm install konva@^10.2 react-konva@^19.2 zustand@^5.0 zundo@^2.3

# Already in project (verify versions)
# @supabase/supabase-js@^2.100  (existing)
# zod@^3.22                      (existing)

# Dev
npm install -D @types/konva  # if needed, but konva ships its own types
```

---

## Installation Commands

### Python snap engine deps (zero new -- validation only)

```bash
# Verify existing deps cover requirements
python -c "
from scipy.cluster.hierarchy import DisjointSet
from scipy.spatial import KDTree
from numpy.linalg import lstsq, solve
from shapely.validation import make_valid
print('All snap engine deps present')
"
```

### Python API sidecar deps

```bash
pip install 'fastapi>=0.115' 'pydantic>=2.10' 'uvicorn>=0.30'
```

### Python test deps

```bash
pip install 'pytest>=8.0' 'pytest-cov>=5.0'
```

### Frontend deps

```bash
npm install konva@^10.2 react-konva@^19.2 zustand@^5.0 zundo@^2.3
```

---

## Sources

### Verified with Context7 (HIGH confidence)
- [SciPy DisjointSet](https://docs.scipy.org/doc/scipy/reference/generated/scipy.cluster.hierarchy.DisjointSet.html) -- API: add, merge, connected, __getitem__, subset, subsets. Path halving + merge by size. Added v1.6.0.
- [SciPy KDTree](https://docs.scipy.org/doc/scipy/reference/generated/scipy.spatial.KDTree.html) -- query_ball_point for radius search.
- [numpy.linalg.lstsq](https://numpy.org/doc/stable/reference/generated/numpy.linalg.lstsq.html) -- NumPy v2.4 docs. Returns x, residuals, rank, singular values.
- [scipy.linalg.lstsq](https://docs.scipy.org/doc/scipy/reference/generated/scipy.linalg.lstsq.html) -- SciPy v1.17.0 docs. Similar API, chose numpy version for consistency with existing codebase.
- [Shapely unary_union, snap, make_valid](https://shapely.readthedocs.io/en/stable/) -- Shapely 2.1.2 docs.
- [Pydantic v2 BaseModel, field_validator, model_validator](https://docs.pydantic.dev/latest/) -- Pydantic 2.13.2 docs.
- [React Konva events, Stage/Layer/shapes](https://konvajs.org/docs/react/index.html) -- react-konva 19.x docs.
- [Zustand temporal middleware ecosystem](https://zustand.docs.pmnd.rs/) -- Zustand 5.x docs.
- [Supabase Realtime Postgres Changes](https://supabase.com/docs/guides/realtime/postgres-changes) -- subscribe to INSERT/UPDATE/DELETE with filter syntax.

### Verified with official docs/PyPI/npm (HIGH confidence)
- [FastAPI 0.135.x](https://pypi.org/project/fastapi/) -- Python 3.10+ after 0.130.0.
- [Konva 10.2.5](https://www.npmjs.com/package/konva) -- Published April 2026.
- [react-konva 19.2.3](https://www.npmjs.com/package/react-konva) -- Published February 2026.
- [Zustand 5.0.11](https://www.npmjs.com/package/zustand) -- Published January 2026.
- [zundo 2.3.0](https://www.npmjs.com/package/zundo) -- temporal middleware, <700 bytes, partialize option.
- [@supabase/supabase-js 2.103.2](https://www.npmjs.com/package/@supabase/supabase-js) -- Published April 2026.
- [SciPy 1.17.1](https://pypi.org/project/SciPy/) -- Released February 2026.
- [NumPy 2.4.4](https://pypi.org/project/numpy/) -- Released March 2026.
- [Shapely 2.1.2](https://pypi.org/project/shapely/) -- BSD licensed, GEOS backend.
- [Pydantic 2.13.2](https://pypi.org/project/pydantic/) -- Released April 2026.
- [pytest 9.0.3](https://pypi.org/project/pytest/) -- Released April 2026.

### WebSearch verified (MEDIUM confidence)
- [Konva vs Fabric.js comparison](https://dev.to/lico/react-comparison-of-js-canvas-libraries-konvajs-vs-fabricjs-1dan) -- Scene graph vs flat model, memory management differences.
- [zundo GitHub](https://github.com/charkour/zundo) -- undo/redo/clear/pastStates/futureStates API, partialize and limit options.

---

*Stack analysis: 2026-04-18*
