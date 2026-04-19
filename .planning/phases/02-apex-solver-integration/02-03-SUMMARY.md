---
phase: 02-apex-solver-integration
plan: 03
subsystem: geometry
tags: [shapely, densification, validation, repair, tdd, edge-walking]

# Dependency graph
requires:
  - phase: 02-apex-solver-integration
    plan: 01
    provides: "solve_apices() function, _z_on_plane helper, conftest.py shared fixtures"
  - phase: 01-feature-graph-clustering
    provides: "feature graph (graph.py), winding normalization (winding.py), clustering (clustering.py)"
provides:
  - "densify_edges() function for shared-edge vertex synchronization"
  - "validate_polygons() function with two-pass Shapely validation and graduated repair"
  - "Copy-on-write edge-walking densification pattern"
  - "3D reconstruction from repaired 2D coordinates via nearest-neighbor + plane projection"
affects: [02-04]

# Tech tracking
tech-stack:
  added: []
  patterns: ["edge-walking densification with parameter-t sorting", "two-pass validation (read-only diagnostic + repair gate)", "graduated area-change tolerance (D-05)", "MultiPolygon largest-piece extraction (D-06)", "GeometryCollection polygon extraction"]

key-files:
  created:
    - roof_pipeline/panel_snap_v2/densify.py
    - roof_pipeline/panel_snap_v2/validate.py
    - roof_pipeline/panel_snap_v2/tests/test_densify.py
    - roof_pipeline/panel_snap_v2/tests/test_validate.py
  modified: []

key-decisions:
  - "Copied _z_on_plane and _point_to_segment_dist_xy into densify.py rather than cross-importing from solver.py or snapping.py (snapping.py being superseded)"
  - "GeometryCollection handling added alongside MultiPolygon -- make_valid returns GeometryCollection with LineString debris on notch-style self-intersections"
  - "3D reconstruction uses nearest-neighbor match (1e-8 threshold) for vertices close to originals, plane inverse projection for relocated vertices"
  - "Test fixtures use asymmetric bowties (ratio > 0.95) for MultiPolygon tests and notch patterns for area-change threshold tests"

patterns-established:
  - "Edge-walking with parameter-t sorted insertions and endpoint dedup from snapping.py adapted for feature-graph-driven shared edges"
  - "Two-pass validation pattern: stage='solver' (DEBUG, read-only) then stage='densify' (WARNING, repair)"

requirements-completed: [TOPO-09, TOPO-10, TEST-06]

# Metrics
duration: 9min
completed: 2026-04-19
---

# Phase 2 Plan 03: Densify + Validate Summary

**Edge-walking densification for shared-edge vertex synchronization and two-pass Shapely validation with graduated area-change repair thresholds**

## Performance

- **Duration:** 9 min
- **Started:** 2026-04-19T02:56:47Z
- **Completed:** 2026-04-19T03:06:00Z
- **Tasks:** 3
- **Files modified:** 4

## Accomplishments
- Implemented `densify.py` with `densify_edges()` that walks feature-graph edges to insert shared-edge vertices sorted by parameter t, with endpoint dedup preventing duplicate insertions within tolerance distance
- Implemented `validate.py` with `validate_polygons()` providing two-pass validation: read-only diagnostic (solver stage, DEBUG) and repair gate (densify stage, WARNING/ERROR)
- Graduated area-change tolerance per D-05: < 0.1% silent, 0.1-1% WARNING, >= 1% RuntimeError
- MultiPolygon handling per D-06: keep largest piece if ratio >= 0.95, otherwise RuntimeError
- GeometryCollection handling for make_valid results that include LineString debris
- 3D reconstruction from repaired 2D coordinates using nearest-neighbor match + plane inverse projection
- All 36 tests pass (25 prior + 3 densify + 8 validate)

## Task Commits

Each task was committed atomically:

1. **Task 1: RED -- Write failing densify and validate tests** - `8579240` (test)
2. **Task 2: GREEN -- Implement densify.py** - `cad4df8` (feat)
3. **Task 3: GREEN -- Implement validate.py** - `52f75e2` (feat)

## TDD Gate Compliance

- RED gate: `8579240` (test commit -- 11 tests fail with ModuleNotFoundError)
- GREEN gate (densify): `cad4df8` (feat commit -- 3 densify tests pass)
- GREEN gate (validate): `52f75e2` (feat commit -- all 36 tests pass)
- REFACTOR gate: not needed (code clean from initial implementation)

## Files Created/Modified
- `roof_pipeline/panel_snap_v2/densify.py` - Edge-walking densification with densify_edges(), _z_on_plane, _point_to_segment_dist_xy helpers
- `roof_pipeline/panel_snap_v2/validate.py` - Two-pass Shapely validation with validate_polygons(), graduated area tolerance, MultiPolygon/GeometryCollection handling, 3D reconstruction
- `roof_pipeline/panel_snap_v2/tests/test_densify.py` - 3 tests: shared-edge vertex insertion, t-sorted insertions, endpoint dedup
- `roof_pipeline/panel_snap_v2/tests/test_validate.py` - 8 tests: valid pass-through, self-intersecting repair (TEST-06), solver read-only, area change silent/warning/hard-fail (D-05), MultiPolygon keeps largest/ratio fail (D-06)

## Decisions Made
- `_z_on_plane` and `_point_to_segment_dist_xy` copied into densify.py (not cross-imported) because snapping.py is being superseded and solver.py already has its own copy
- GeometryCollection handling was added alongside MultiPolygon in `_extract_largest_polygon()` because Shapely's `make_valid()` returns GeometryCollection (not MultiPolygon) for notch-style self-intersections that produce LineString debris
- Test fixtures for area-change tests use notch patterns (rectangle with overlapping notch) instead of bowties, because bowties produce two equal-area triangles that trigger the ratio check before the area check
- Asymmetric bowties (one tiny triangle, one large) used for TEST-06 and MultiPolygon tests to ensure ratio > 0.95

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed test fixture geometry for sorted-insertions test**
- **Found during:** Task 2 (GREEN phase)
- **Issue:** Original test used shared edge from x=0 to x=4 with extra vertices at x=1 and x=3. With tol=1.0, these vertices are exactly tol distance from endpoints, triggering endpoint dedup.
- **Fix:** Extended shared edge from x=0 to x=10 with extra vertices at x=3 and x=7 (well beyond tol from endpoints)
- **Files modified:** roof_pipeline/panel_snap_v2/tests/test_densify.py
- **Commit:** cad4df8

**2. [Rule 1 - Bug] Fixed test fixture geometry for self-intersecting repair test**
- **Found during:** Task 3 (GREEN phase)
- **Issue:** Symmetric bowtie (0,0)-(2,2)-(2,0)-(0,2) produces two equal-area triangles (ratio 0.5), triggering the MultiPolygon ratio error before reaching the repair assertion.
- **Fix:** Changed to asymmetric bowtie (0,0)-(10,0.1)-(10,0)-(0,10) which produces one large triangle and one tiny triangle (ratio 0.9999)
- **Files modified:** roof_pipeline/panel_snap_v2/tests/test_validate.py
- **Commit:** 52f75e2

**3. [Rule 1 - Bug] Fixed test fixture for area-change hard-fail test**
- **Found during:** Task 3 (GREEN phase)
- **Issue:** Symmetric bowtie triggers MultiPolygon ratio error (with message about "largest piece ratio") instead of area-change error. Test expected "repair changed polygon area" message.
- **Fix:** Changed to notch pattern (rectangle with large overlapping notch) that produces GeometryCollection with single polygon piece, causing 2.9% area change that triggers the area-change hard-fail
- **Files modified:** roof_pipeline/panel_snap_v2/tests/test_validate.py
- **Commit:** 52f75e2

**4. [Rule 1 - Bug] Fixed multipolygon_keeps_largest test to use smaller area change**
- **Found during:** Task 3 (GREEN phase)
- **Issue:** Initial asymmetric bowtie had 1.01% area change (just barely exceeding 1% hard-fail), causing RuntimeError before MultiPolygon WARNING assertion could be checked.
- **Fix:** Used a more asymmetric bowtie (0,0)-(10,0.1)-(10,0)-(0,10) with only 0.01% area change
- **Files modified:** roof_pipeline/panel_snap_v2/tests/test_validate.py
- **Commit:** 52f75e2

**5. [Rule 2 - Critical] Added GeometryCollection handling in validate.py**
- **Found during:** Task 3 (GREEN phase)
- **Issue:** Shapely's make_valid() returns GeometryCollection (not MultiPolygon) for notch-style self-intersections that produce LineString debris alongside the repaired polygon. The plan only mentioned MultiPolygon handling.
- **Fix:** Added GeometryCollection to the isinstance check in _extract_largest_polygon(), filtering for Polygon pieces only
- **Files modified:** roof_pipeline/panel_snap_v2/validate.py
- **Commit:** 52f75e2

---

**Total deviations:** 5 auto-fixed (4 test fixture bugs, 1 missing critical functionality)
**Impact on plan:** All fixes corrected test fixture geometry and added necessary GeometryCollection handling. No scope creep -- core algorithms unchanged.

## Issues Encountered
None beyond the test fixture and GeometryCollection issues documented as deviations above.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- `densify_edges()` and `validate_polygons()` are ready for integration into `snap_polygons()` in Plan 02-04
- Both functions follow copy-on-write pattern and accept the same `(polygons, planes)` signature
- All 36 tests green -- safe to build on

---
*Phase: 02-apex-solver-integration*
*Completed: 2026-04-19*

## Self-Check: PASSED
