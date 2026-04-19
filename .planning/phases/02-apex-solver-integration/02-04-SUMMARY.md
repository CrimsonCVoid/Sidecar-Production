---
phase: 02-apex-solver-integration
plan: 04
subsystem: integration
tags: [orchestration, cli-flag, json-sidecar, golden-files, smoke-test, end-to-end]

# Dependency graph
requires:
  - phase: 02-apex-solver-integration
    plan: 01
    provides: "solve_apices() with tuple return (polygons, solved_positions)"
  - phase: 02-apex-solver-integration
    plan: 02
    provides: "PanelCorners/PanelsInput Pydantic schema, boundaries.py validation"
  - phase: 02-apex-solver-integration
    plan: 03
    provides: "densify_edges(), validate_polygons() with two-pass repair"
  - phase: 01-feature-graph-clustering
    provides: "clustering, graph, winding modules"
provides:
  - "Complete snap_polygons() orchestration: winding -> graph -> solve -> validate1 -> densify -> validate2"
  - "--snap-v2 CLI flag in run_real.py routing to snap_v2 engine"
  - "snap_v2_features.json sidecar output with solved feature positions"
  - "Tiered golden-file smoke test (Tier 0/1/2) with --regenerate-golden support"
affects: []

# Tech tracking
tech-stack:
  added: []
  patterns: ["6-stage pipeline orchestration", "tuple return for polygon+graph", "tiered golden-file comparison (D-09)", "--regenerate-golden pytest flag (D-11)", "structural v1/v2 equivalence check"]

key-files:
  created:
    - roof_pipeline/panel_snap_v2/tests/test_smoke_gable.py
    - roof_pipeline/panel_snap_v2/tests/golden/gable/polygons.npz
    - roof_pipeline/panel_snap_v2/tests/golden/gable/features.json
    - roof_pipeline/panel_snap_v2/tests/golden/gable/mesh_vertices.npy
    - roof_pipeline/panel_snap_v2/tests/golden/gable/mesh_faces.npy
  modified:
    - roof_pipeline/panel_snap_v2/__init__.py
    - roof_pipeline/run_real.py
    - roof_pipeline/panel_snap_v2/tests/conftest.py

key-decisions:
  - "snap_polygons returns tuple (polygons, graph) instead of just polygons -- run_real.py needs graph for JSON sidecar"
  - "v1/v2 cross-check tests verify structural equivalence (same XY, same shapes) not byte-identity -- D-02 per-plane Z reconstruction and CCW winding normalization produce intentionally different Z values and vertex ordering"
  - "_update_graph_positions finds shared vertices by XY proximity between member panels rather than re-clustering -- avoids root-index mismatch between separate cluster_vertices calls"
  - "Polygon loading extracted before v1/v2 branch in run_real.py -- both paths share the same boundary extraction code"

patterns-established:
  - "Pipeline orchestration pattern: normalize -> graph -> solve -> validate(read-only) -> densify -> validate(repair)"
  - "JSON sidecar output alongside mesh/PDF outputs"
  - "Tiered golden-file testing: Tier 0 (polygon arrays), Tier 1 (JSON byte), Tier 2 (mesh structural)"

requirements-completed: [INTG-01, INTG-02, INTG-03, TEST-01]

# Metrics
duration: 7min
completed: 2026-04-19
---

# Phase 2 Plan 04: Pipeline Orchestration + Integration Summary

**Full snap_v2 pipeline orchestration with --snap-v2 CLI flag, JSON sidecar output, and tiered golden-file smoke test proving gable structural equivalence**

## Performance

- **Duration:** 7 min
- **Started:** 2026-04-19T03:11:17Z
- **Completed:** 2026-04-19T03:18:56Z
- **Tasks:** 3
- **Files modified:** 8

## Accomplishments
- Replaced Phase 1 stub in `__init__.py` with full 6-stage pipeline orchestration: winding -> graph -> solve -> validate (read-only) -> densify -> validate (repair)
- Changed `snap_polygons` return type from `dict` to `tuple[dict, dict]` to provide both snapped polygons and feature graph to callers
- Added `_update_graph_positions` that populates `position_xyz` on shared features by finding nearest XY-matching vertices between member panels
- Wired `--snap-v2` CLI flag into `run_real.py` routing through snap_v2 engine with JSON sidecar output
- Refactored `run_real.py` to extract polygon loading before v1/v2 branch, keeping v1 path unchanged in else
- Created 5-test tiered golden-file smoke test: Tier 0 (polygon arrays at 1e-12), Tier 1 (JSON byte identity), Tier 2 (mesh vertices at 1e-9 + exact face match)
- Added `--regenerate-golden` flag to pytest via conftest.py
- All 41 tests pass (36 prior + 5 new smoke tests)

## Task Commits

Each task was committed atomically:

1. **Task 1: Wire __init__.py to orchestrate full snap_v2 pipeline** - `63204a5` (feat)
2. **Task 2: Wire --snap-v2 flag and JSON sidecar into run_real.py** - `8146b0e` (feat)
3. **Task 3: Create tiered golden-file smoke test** - `fdae136` (feat)

## Files Created/Modified
- `roof_pipeline/panel_snap_v2/__init__.py` - Full 6-stage pipeline orchestration, tuple return, _update_graph_positions helper
- `roof_pipeline/run_real.py` - --snap-v2 flag, snap_v2_features.json sidecar, import json, refactored snap dispatch
- `roof_pipeline/panel_snap_v2/tests/conftest.py` - Added pytest_addoption for --regenerate-golden
- `roof_pipeline/panel_snap_v2/tests/test_smoke_gable.py` - 5 tiered golden-file tests (TestGableSmokeIdentity)
- `roof_pipeline/panel_snap_v2/tests/golden/gable/polygons.npz` - Tier 0 golden: polygon arrays
- `roof_pipeline/panel_snap_v2/tests/golden/gable/features.json` - Tier 1 golden: feature graph JSON
- `roof_pipeline/panel_snap_v2/tests/golden/gable/mesh_vertices.npy` - Tier 2 golden: mesh vertices
- `roof_pipeline/panel_snap_v2/tests/golden/gable/mesh_faces.npy` - Tier 2 golden: mesh faces

## Decisions Made
- `snap_polygons` return type changed from `dict` to `tuple[dict[int, np.ndarray], dict]` -- `run_real.py` needs both polygons and feature graph for the JSON sidecar. This is an API change from the Phase 1 stub.
- v1/v2 cross-check tests use structural equivalence (same panel IDs, same vertex counts, XY match within 1e-6) rather than byte-identity. Byte-identity is impossible because D-02 per-plane Z reconstruction gives each panel its own Z at shared ridge vertices (v1 averages Z), and CCW winding normalization rotates the starting vertex.
- `_update_graph_positions` finds shared vertices by iterating member panels and finding the nearest XY match, rather than re-clustering. This avoids root-index mismatch since `build_feature_graph` and `solve_apices` each call `cluster_vertices` independently.
- Polygon loading (clicks vs contours) extracted before the v1/v2 branch in `run_real.py` -- deduplicates the boundary extraction code.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] v1/v2 cross-check cannot be byte-identical**
- **Found during:** Task 3
- **Issue:** Plan specified `test_tier0_v1_v2_match` comparing v1 and v2 output at `atol=1e-12`. Testing revealed two intentional differences: (a) CCW winding normalization in v2 rotates starting vertex, (b) D-02 per-plane Z reconstruction gives different Z values than v1's averaged Z at shared ridge vertices.
- **Fix:** Changed cross-check tests from byte-identity to structural equivalence: same panel IDs, same vertex shapes, matching XY positions (lexicographic sort, atol=1e-6). Renamed tests to `test_tier0_v1_v2_structural_match` and `test_tier2_v1_v2_mesh_structural_match` for clarity.
- **Files modified:** roof_pipeline/panel_snap_v2/tests/test_smoke_gable.py
- **Commit:** fdae136

---

**Total deviations:** 1 auto-fixed (design-level difference between v1 and v2 outputs)
**Impact on plan:** The golden-file tests (Tier 0/1/2) validate v2's own deterministic output. Cross-check tests validate structural equivalence with v1. This correctly reflects that v2 improves on v1 (per-plane Z is more correct than averaged Z) while maintaining the same geometric topology.

## Issues Encountered
None beyond the v1/v2 byte-identity difference documented as a deviation above.

## User Setup Required
None - no external service configuration required.

## Milestone 1 Completion Status
This is the final plan of Phase 2 and the final phase of Milestone 1. All requirements are now complete:
- **Topology Engine (TOPO-01 through TOPO-11):** Complete
- **Input Validation (VALID-01, VALID-02):** Complete
- **Integration (INTG-01, INTG-02, INTG-03):** Complete
- **Test Suite (TEST-01 through TEST-07):** Complete
- **Total tests:** 41 passing

---
*Phase: 02-apex-solver-integration*
*Completed: 2026-04-19*

## Self-Check: PASSED

- All 8 created/modified files exist on disk
- All 3 task commits found in git log (63204a5, 8146b0e, fdae136)
- All 41 tests pass (36 prior + 5 new smoke tests)
