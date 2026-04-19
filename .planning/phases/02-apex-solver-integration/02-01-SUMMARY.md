---
phase: 02-apex-solver-integration
plan: 01
subsystem: geometry
tags: [numpy, linalg, apex-solver, plane-intersection, least-squares, tdd]

# Dependency graph
requires:
  - phase: 01-feature-graph-clustering
    provides: "union-find clustering (clustering.py), feature graph (graph.py), winding normalization (winding.py)"
provides:
  - "solve_apices() function with valence-aware dispatch (2/3/4+)"
  - "Shared _make_plane test fixture in conftest.py"
  - "Condition-number guards (_COND_WARN=1e8, _COND_FAIL=1e12)"
  - "_z_on_plane() helper for per-plane Z reconstruction"
affects: [02-02, 02-03, 02-04]

# Tech tracking
tech-stack:
  added: []
  patterns: ["valence-dispatch solver", "condition-number guard with centroid fallback", "tuple return for downstream position propagation"]

key-files:
  created:
    - roof_pipeline/panel_snap_v2/solver.py
    - roof_pipeline/panel_snap_v2/tests/test_solver.py
    - roof_pipeline/panel_snap_v2/tests/conftest.py
  modified:
    - roof_pipeline/panel_snap_v2/tests/test_clustering.py
    - roof_pipeline/panel_snap_v2/tests/test_graph.py
    - roof_pipeline/panel_snap_v2/tests/test_winding.py

key-decisions:
  - "solve_apices returns tuple (polygons, solved_positions) for downstream graph position update per 02-CONTEXT.md review note"
  - "Weighted lstsq uses 1.0/max(rms_residual, 1e-6) to prevent divide-by-zero on perfectly-fit planes"
  - "_z_on_plane copied into solver.py rather than imported from snapping.py (snapping.py being superseded)"

patterns-established:
  - "Shared test fixtures in conftest.py imported via from .conftest import _make_plane"
  - "Plane cross-product helper _plane_from_triangle for test fixture construction"

requirements-completed: [TOPO-05, TOPO-06, TOPO-07, TOPO-08, TEST-02, TEST-03]

# Metrics
duration: 7min
completed: 2026-04-18
---

# Phase 2 Plan 01: Apex Solver Summary

**Valence-aware apex solver with 3-plane intersection, weighted least-squares, and condition-number guards for hip/ridge vertex welding**

## Performance

- **Duration:** 7 min
- **Started:** 2026-04-19T02:38:50Z
- **Completed:** 2026-04-19T02:46:05Z
- **Tasks:** 3
- **Files modified:** 6

## Accomplishments
- Extracted shared `_make_plane` fixture into `conftest.py`, eliminating duplication across 3 test files
- Implemented `solver.py` with valence-aware dispatch: valence-2 (XY centroid + per-plane Z), valence-3 (3-plane intersection via `np.linalg.solve`), valence-4+ (weighted least-squares via `np.linalg.lstsq`)
- Condition-number guards prevent degenerate solutions: WARNING fallback at cond > 1e8, RuntimeError at cond > 1e12
- All 17 tests pass (12 prior + 5 new solver tests covering TEST-02, TEST-03, TOPO-05, D-01 fallback, D-01 hard-fail)

## Task Commits

Each task was committed atomically:

1. **Task 0: Extract shared test fixture into conftest.py** - `80d7d55` (refactor)
2. **Task 1: RED -- Write failing solver tests** - `a950a59` (test)
3. **Task 2: GREEN -- Implement solver.py to pass all tests** - `bd05820` (feat)

## TDD Gate Compliance

- RED gate: `a950a59` (test commit -- 5 tests fail with ModuleNotFoundError)
- GREEN gate: `bd05820` (feat commit -- all 17 tests pass)
- REFACTOR gate: not needed (code clean from initial implementation)

## Files Created/Modified
- `roof_pipeline/panel_snap_v2/solver.py` - Valence-aware apex solver with solve_apices(), condition-number guards, _z_on_plane helper
- `roof_pipeline/panel_snap_v2/tests/test_solver.py` - 5 tests: hip apex weld (TEST-02), ridge weld (TEST-03), valence-2 centroid (TOPO-05), condition fallback, condition hard-fail
- `roof_pipeline/panel_snap_v2/tests/conftest.py` - Shared _make_plane helper for all test files
- `roof_pipeline/panel_snap_v2/tests/test_clustering.py` - Import _make_plane from conftest
- `roof_pipeline/panel_snap_v2/tests/test_graph.py` - Import _make_plane from conftest
- `roof_pipeline/panel_snap_v2/tests/test_winding.py` - Import _make_plane from conftest

## Decisions Made
- `solve_apices` returns `tuple[dict, dict]` (polygons, solved_positions) per 02-CONTEXT.md review note -- second element maps cluster_root to solved xyz for downstream graph position update in Plan 02-04
- Weighted lstsq uses `1.0 / max(rms_residual, 1e-6)` to prevent divide-by-zero on planes with zero residual (perfectly-fit synthetic planes)
- `_z_on_plane` copied into solver.py rather than imported from `snapping.py` because `snapping.py` is being superseded by the v2 engine

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed test fixture geometry for condition-number tests**
- **Found during:** Task 2 (GREEN phase)
- **Issue:** Original test fixture used 3 panels with collinear vertices in one panel (apex at (0,0,5), vertices at (-2,0,5) and (2,0,5) -- all on X-axis). Shapely detected this as non-simple polygon and raised TopologicalError during winding normalization. Also, near-parallel plane normals with eps=0.001 only produced cond=3e3, not > 1e8.
- **Fix:** Restructured test panels to use 120-degree sector triangles (non-degenerate in any 2D projection). Changed epsilon for near-parallel normals from 0.001 to 1e-8 (produces cond ~3e8, correctly triggering fallback).
- **Files modified:** roof_pipeline/panel_snap_v2/tests/test_solver.py
- **Verification:** All 5 solver tests pass
- **Committed in:** bd05820 (Task 2 commit)

**2. [Rule 1 - Bug] Fixed valence-2 test to use 3D-close shared vertices**
- **Found during:** Task 2 (GREEN phase)
- **Issue:** Original shared vertices had Z values of 5.0 and 7.0, giving 3D distance ~2.0 which exceeds tol=0.5. Vertices did not cluster. Also assumed vertex index 0 would remain stable after winding normalization.
- **Fix:** Changed p2_shared Z from 7.0 to 5.01 (within 3D tol). Added `_find_nearest_vertex` helper to locate the solved vertex by XY proximity instead of assuming fixed index.
- **Files modified:** roof_pipeline/panel_snap_v2/tests/test_solver.py
- **Verification:** Valence-2 test passes with correct XY centroid and per-plane Z
- **Committed in:** bd05820 (Task 2 commit)

---

**Total deviations:** 2 auto-fixed (2 bugs in test fixtures)
**Impact on plan:** Both fixes corrected test fixture geometry to produce valid inputs for winding normalization and correct condition numbers. No scope creep -- solver implementation unchanged.

## Issues Encountered
None beyond the test fixture geometry issues documented as deviations above.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- `solve_apices()` is ready for integration into `snap_polygons()` in Plan 02-04
- Returns tuple format matches what `_update_graph_positions()` will consume in Plan 02-04
- All 17 tests green -- safe to build on

---
*Phase: 02-apex-solver-integration*
*Completed: 2026-04-18*

## Self-Check: PASSED

- All 3 created files exist on disk
- All 3 task commits found in git log (80d7d55, a950a59, bd05820)
- All 17 tests pass (12 prior + 5 new)
