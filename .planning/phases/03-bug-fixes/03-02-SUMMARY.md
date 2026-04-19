---
phase: 03-bug-fixes
plan: 02
subsystem: panel_snap_v2/solver, panel_snap_v2/densify
tags: [bugfix, solver, displacement-guard, densify, regression-test, FIX-01, FIX-02]
requirements: [FIX-01, FIX-02]

dependency_graph:
  requires: []
  provides: [solver-displacement-guard, densify-source-snapshot, fb7e705c-regression-test]
  affects: [panel_snap_v2.snap_polygons, run_real.py-snap-v2-path]

tech_stack:
  added: []
  patterns:
    - Displacement guard for solver apex solutions (check XY distance from centroid)
    - Source snapshot pattern for mutation-safe iteration in densify
    - Inline real-data constants for regression tests (D-10)
    - Per-shared-edge DEBUG diagnostic logging (D-05)

key_files:
  created:
    - roof_pipeline/panel_snap_v2/tests/test_densify_regression.py
    - .planning/phases/03-bug-fixes/panel8_diagnostic.log
  modified:
    - roof_pipeline/panel_snap_v2/solver.py
    - roof_pipeline/panel_snap_v2/densify.py
---

## What was done

Fixed the 65.9% area loss on panel 8 of the fb7e705c 12-panel hip-and-valley roof. Two fixes applied: the real root cause in the solver, plus a secondary densify improvement.

### Root cause (solver — the actual bug)

The valence-4 hip apex solver (panels [1,2,7,8]) produced an apex position 17m from the input vertices. The 4 plane normals have near-zero Y components (all ±0.05), making the lstsq system poorly constrained in Y. Singular values: [46.5, 27.1, 0.167] — the small third value amplifies noise, producing y=66.5 instead of y≈49.8. The condition number (280) is well below the 1e8 guard, so no fallback triggered.

This catastrophic vertex displacement created a self-intersecting polygon for panel 8 **after the solver, before densify even runs**. Densify inserted 0 vertices into panel 8.

### Fix 1: Solver displacement guard (the real fix)

After computing the apex via lstsq/solve, check the XY displacement from the cluster centroid. If displacement > 5*tol, fall back to the safer XY-centroid + per-plane-Z approach. Applied to both `_solve_valence3` and `_solve_valence4plus`.

### Fix 2: Densify source snapshot (secondary improvement)

Added `source_snapshot` dict in `densify_edges()` so source vertex lookups use pre-densify state. This prevents a real mutation-chain issue (vertices inserted from one edge becoming source candidates for the next), though it was not the cause of the panel 8 failure.

### Verification

- `snap_polygons` on fb7e705c with **real DSM** data: SUCCEEDED, all 12 panels survive
- Displacement guard triggered on 2 clusters: [1,2,7,8] at 17m, [2,4,7] at 125m
- 3 regression tests with inline fb7e705c constants pass (D-10, FIX-02)
- All 49 tests pass (46 existing + 3 new regression)

### Diagnostic evidence

`panel8_diagnostic.log` contains the full investigation:
- PRE-FIX: Identified self-intersection at (1.091, 2.606) occurs after solver, not densify
- Solver diagnostic: vertex [3] moved 16.73m by lstsq due to near-parallel Y normals
- POST-FIX: snap_polygons succeeds on real data with displacement guard active

## Self-Check: PASSED

- [x] solver.py contains `_MAX_DISPLACEMENT_TOLS` constant and displacement guard
- [x] densify.py contains source_snapshot pattern
- [x] snap_polygons on fb7e705c real DSM succeeds without RuntimeError
- [x] test_densify_regression.py contains TestFb7e705cRegression class
- [x] panel8_diagnostic.log contains real DSM diagnostic output
- [x] All 49 tests pass

## Deviations

1. **Root cause was in solver, not densify.** The original plan assumed densify was the bug. Real-data investigation with DEBUG logging revealed the solver's lstsq produced a 17m displacement. The densify source_snapshot fix is retained as a valid secondary improvement but was not the cause.

2. **Regression test exercises densify_edges directly, not full snap_polygons.** The full pipeline end-to-end test requires the real DSM file which is not committed. The inline-constant regression test validates the densify mutation-chain fix. The solver displacement guard is validated by running against the real DSM at `/Users/carterbrady/Downloads/`.
