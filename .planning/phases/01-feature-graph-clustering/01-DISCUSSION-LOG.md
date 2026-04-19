# Phase 1: Feature Graph + Clustering - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md -- this log preserves the alternatives considered.

**Date:** 2026-04-18
**Phase:** 01-feature-graph-clustering
**Areas discussed:** Dry-run output format, Subpackage layout, Non-convex winding

---

## Dry-run output format

| Option | Description | Selected |
|--------|-------------|----------|
| JSON to stdout | Machine-parseable JSON matching snap_v2_features.json schema. Easy to pipe to jq. | |
| Text summary table | Human-readable table with feature nodes, valence counts, edge listings. | |
| Both (JSON + log summary) | JSON to stdout for piping, plus human-readable summary to stderr via logging. | ✓ |

**User's choice:** Both (JSON + log summary)
**Notes:** None

### Follow-up: Schema for unsolved nodes

| Option | Description | Selected |
|--------|-------------|----------|
| Same schema, nulls for unsolved | Full INTG-02 schema, position_xyz is null for unsolved. One schema to learn. | ✓ |
| Centroid placeholder | Full schema but fill position_xyz with cluster centroid for debugging. | |

**User's choice:** Same schema, nulls for unsolved
**Notes:** Forward compatibility — Phase 2 fills in the solved positions.

---

## Subpackage layout

| Option | Description | Selected |
|--------|-------------|----------|
| Subpackage directory | roof_pipeline/panel_snap_v2/ with __init__.py, winding.py, clustering.py, graph.py | ✓ |
| Single module | roof_pipeline/panel_snap_v2.py — everything in one file | |
| Two files split | panel_snap_v2.py for Phase 1, panel_snap_v2_solver.py for Phase 2 | |

**User's choice:** Subpackage directory
**Notes:** Phase 2 adds solver.py, densify.py, validate.py to the same subpackage.

### Follow-up: Test location

| Option | Description | Selected |
|--------|-------------|----------|
| Inside subpackage | panel_snap_v2/tests/ with per-module test files | ✓ |
| Top-level test file | roof_pipeline/panel_snap_v2_test.py at package root | |
| You decide | Let Claude pick during planning | |

**User's choice:** Inside subpackage
**Notes:** ROADMAP test invocation path adjusts from `pytest roof_pipeline/panel_snap_v2_test.py` to `pytest roof_pipeline/panel_snap_v2/tests/`.

---

## Non-convex winding

| Option | Description | Selected |
|--------|-------------|----------|
| Shapely orientation | Project to 2D, use shapely.geometry.polygon.orient(sign=1.0) for CCW | ✓ |
| Signed-area with Shapely guard | Shoelace fast path, Shapely fallback for non-simple polygons | |
| Pure Shapely always | Always use Shapely orient(), no branching | |

**User's choice:** Shapely orientation
**Notes:** User provided three critical implementation constraints:
1. Projection uses orthonormal 2D basis from plane normal via numpy.cross — no naive XY-drop (fails on steep pitch)
2. Reorder applied to original 3D array via permutation tracking — no round-trip FP drift
3. TopologicalError on self-intersecting input must fail with panel ID — no catch-and-continue (repair is Phase 2 TOPO-10)
4. Three required tests: TEST-07 (L-shape), test_steep_plane_winding (60 degrees), test_self_intersecting_raises (bowtie)

---

## Claude's Discretion

- Internal helper function naming/decomposition
- Union-find DisjointSet usage patterns
- Feature graph internal data structure choice
- Logging verbosity within stages

## Deferred Ideas

None — discussion stayed within phase scope
