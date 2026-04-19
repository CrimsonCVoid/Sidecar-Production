# Phase 1: Feature Graph + Clustering - Context

**Gathered:** 2026-04-18
**Status:** Ready for planning

<domain>
## Phase Boundary

Pure Python subpackage (`panel_snap_v2`) that normalizes per-panel winding (including non-convex L-shaped panels), clusters vertices with three-pass expanding tolerance, and builds a feature graph. Exposed via `--snap-v2-dryrun` flag that prints the graph and exits without invoking the solver or modifying any downstream module. The solver, edge densification, Shapely validation pass, and `--snap-v2` integration are Phase 2.

</domain>

<decisions>
## Implementation Decisions

### Dry-run output format
- **D-01:** `--snap-v2-dryrun` outputs JSON to stdout and a human-readable log summary to stderr
- **D-02:** JSON uses the full INTG-02 `snap_v2_features.json` schema. `position_xyz` is `null` for unsolved nodes (solver is Phase 2). One schema to learn across both phases.
- **D-03:** stderr log summary shows total node/edge counts and valence distribution (e.g., "valence-2: 3 nodes, valence-3: 1 node")

### Subpackage layout
- **D-04:** `panel_snap_v2` is a subpackage directory under `roof_pipeline/`, not a single module. `__init__.py` exports `snap_polygons()` as the public API.
- **D-05:** Phase 1 internal modules: `winding.py` (CCW normalization), `clustering.py` (union-find 3-pass), `graph.py` (feature graph construction)
- **D-06:** Phase 2 will add: `solver.py` (apex solving), `densify.py` (edge densification), `validate.py` (Shapely checks)
- **D-07:** Tests live inside the subpackage at `panel_snap_v2/tests/` with per-module test files (`test_winding.py`, `test_clustering.py`, `test_graph.py`). ROADMAP test invocation adjusts to `pytest roof_pipeline/panel_snap_v2/tests/`

### Non-convex winding algorithm
- **D-08:** Use `shapely.geometry.polygon.orient(poly, sign=1.0)` to enforce CCW winding. Handles convex and non-convex (L-shaped) polygons correctly. Shapely already in requirements.txt.
- **D-09:** Projection to 2D uses the panel plane's normal + centroid to build an orthonormal 2D basis via `numpy.cross`. Do NOT use naive XY-drop — that fails on steep-pitch panels.
- **D-10:** Reordering is applied to the original 3D vertex array by tracking the permutation. Do NOT regenerate 3D from 2D — round-tripping introduces floating-point drift.
- **D-11:** If `shapely.orient()` raises `TopologicalError` on self-intersecting input, fail with the panel ID in the error message. Do NOT catch-and-continue. Repair belongs to Phase 2 (TOPO-10).
- **D-12:** Three winding tests required: TEST-07 (L-shape both windings normalize to same CCW), `test_steep_plane_winding` (60-degree pitch panel where naive XY-drop would flip), `test_self_intersecting_raises` (bowtie polygon raises TopologicalError with panel ID).

### Claude's Discretion
- Internal helper function naming and decomposition within each module
- Exact union-find DisjointSet usage patterns (already decided: `scipy.cluster.hierarchy.DisjointSet`)
- Feature graph internal data structure (dict, dataclass, or namedtuple)
- Logging verbosity within pipeline stages (follow existing `log.info` / `log.warning` patterns)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Existing snap engine (being superseded)
- `roof_pipeline/snapping.py` -- Current pairwise edge snap. Public API: `snap_shared_edges(polygons, tol)` returns `dict[int, ndarray]`. New `snap_polygons` must match this I/O shape (TOPO-01).

### Plane fitting (consumed by winding)
- `roof_pipeline/planes.py` -- `Plane` dataclass (normal, centroid, rms_residual, d). `fit_plane()` and `fit_all_panels()`. Winding normalization needs `Plane.normal` and `Plane.centroid` to build the 2D projection basis.

### Pipeline orchestrator (integration point)
- `roof_pipeline/run_real.py` -- Where `--snap-v2-dryrun` flag will be added. Currently imports from `snapping.py`. Phase 1 adds the flag; Phase 2 wires `--snap-v2`.

### Boundary extraction (upstream data source)
- `roof_pipeline/boundaries.py` -- `polygons_from_clicks()` and `extract_panel_polygons()` produce the `dict[int, ndarray]` input that `panel_snap_v2` consumes.

### Project requirements
- `.planning/REQUIREMENTS.md` -- Phase 1 requirements: TOPO-01, TOPO-02, TOPO-03, TOPO-04, TOPO-11, TEST-04, TEST-05, TEST-07

### Architecture and concerns
- `.planning/codebase/ARCHITECTURE.md` -- Pipeline data flow and layer structure
- `.planning/codebase/CONCERNS.md` -- Known issues including untyped roof dict and input validation gaps

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `planes.Plane` dataclass: normal, centroid, rms_residual, d — consumed by winding normalization for 2D projection basis
- `snapping.snap_shared_edges()` signature: `(polygons: dict[int, ndarray], tol: float) -> dict[int, ndarray]` — `snap_polygons` must match this I/O shape
- `snapping._z_on_plane()`: Z reconstruction from XY + Plane — may be reusable in clustering or solver

### Established Patterns
- Every module uses `log = logging.getLogger(__name__)` for per-module logging
- `from __future__ import annotations` in every file
- Copy-on-write: `out = {pid: poly.copy() for pid, poly in polygons.items()}`
- Functions return concrete types, validate early with shape checks
- Skip invalid items with `log.warning()` + `continue`

### Integration Points
- `run_real.py` argparse: add `--snap-v2-dryrun` flag alongside existing `--snap-tol`, `--no-clicks`, etc.
- Import path: `from .panel_snap_v2 import snap_polygons` from `run_real.py`
- No changes needed to downstream modules (mesh, cutsheets, shop_drawings, ts_export, ts_render_pdf) in Phase 1

</code_context>

<specifics>
## Specific Ideas

- Winding projection must use proper orthonormal basis from plane normal via `numpy.cross` — user explicitly flagged naive XY-drop as a failure mode on steep-pitch panels
- Self-intersecting polygons must fail loudly with panel ID — "do not catch-and-continue" is a hard requirement; repair is Phase 2
- The dry-run JSON schema must be forward-compatible with Phase 2's `snap_v2_features.json` sidecar — one schema to learn

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 01-feature-graph-clustering*
*Context gathered: 2026-04-18*
