---
phase: 03-bug-fixes
verified: 2026-04-19T06:15:00Z
status: passed
score: 3/3 must-haves verified
overrides_applied: 0
must_haves:
  truths:
    - "Running run_real.py --snap-v2 on the 12-panel hip-and-valley roof (fb7e705c) completes without error -- panel 8 passes through densify and Shapely validation without area-change rejection"
    - "A golden-file regression test for the 12-panel hip-and-valley roof exists and passes in the test suite, confirming the densify fix does not regress"
    - "A mask.json file containing duplicate last corners is loaded via polygons_from_clicks and produces the same polygon as the deduplicated version -- no error, no extra zero-length edges"
  artifacts:
    - path: "roof_pipeline/panel_snap_v2/solver.py"
      provides: "Displacement guard for near-parallel plane apex solutions"
    - path: "roof_pipeline/panel_snap_v2/densify.py"
      provides: "Source snapshot pattern for mutation-safe densification"
    - path: "roof_pipeline/panel_snap_v2/schema.py"
      provides: "close-polygon dedup field_validator on PanelCorners.corners_pix"
    - path: "roof_pipeline/panel_snap_v2/tests/test_schema.py"
      provides: "Tests for duplicate-corner dedup behavior"
    - path: "roof_pipeline/panel_snap_v2/tests/test_densify_regression.py"
      provides: "Regression test for 12-panel hip-and-valley roof densify"
    - path: ".planning/phases/03-bug-fixes/panel8_diagnostic.log"
      provides: "Full investigation log with real DSM diagnostic output"
---

# Phase 3: Bug Fixes Verification Report

**Phase Goal:** The snap engine handles complex hip-and-valley roofs without area-loss rejection, and legacy mask.json files with duplicate corners are silently cleaned during ingestion
**Verified:** 2026-04-19T06:15:00Z
**Status:** passed
**Re-verification:** Yes -- re-verified after solver displacement guard fix replaced initial (insufficient) densify-only fix

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Running run_real.py --snap-v2 on fb7e705c completes without error | VERIFIED (real DSM) | `snap_polygons` on fb7e705c with real DSM .tif succeeds. All 12 panels survive. Displacement guard triggers on 2 clusters ([1,2,7,8] at 17m, [2,4,7] at 125m), falling back to centroid. |
| 2 | A regression test for the 12-panel hip-and-valley roof exists and passes | VERIFIED | `test_densify_regression.py` with 3 tests using inline fb7e705c constants. All pass. |
| 3 | A mask.json with duplicate last corners is loaded without error | VERIFIED | `strip_close_polygon_duplicate` validator in schema.py. 5 dedicated tests pass. |

**Score:** 3/3 truths verified.

### Root Cause Investigation

Initial fix attempt targeted densify (source_snapshot pattern). Human verification on real DSM revealed the self-intersection occurs **after the solver, before densify**:

```
panel 8 invalid after solver: Self-intersection[1.09145448364827 2.60565368007058]
```

The valence-4 hip apex solver (panels [1,2,7,8]) produced an apex 17m from input vertices due to near-parallel plane normals in Y (singular values [46.5, 27.1, 0.167]). Condition number (280) was below the 1e8 guard.

Fix: displacement guard in `_solve_valence3` and `_solve_valence4plus` — if solved apex XY distance from cluster centroid exceeds 5*tol, fall back to XY centroid + per-plane Z.

### Requirements Coverage

| Requirement | Plan | Status | Evidence |
|-------------|------|--------|----------|
| FIX-01 | 03-02 | SATISFIED | Solver displacement guard + densify source snapshot. snap_polygons succeeds on fb7e705c real DSM. |
| FIX-02 | 03-02 | SATISFIED | test_densify_regression.py with 3 inline-constant tests. |
| LABEL-01 | 03-01 | SATISFIED | strip_close_polygon_duplicate in schema.py. 5 tests. |

### Test Results

- 49/49 tests pass (13 schema + 6 densify + 5 solver + 6 validate + 4 winding + 5 smoke + 10 other)
- Real DSM end-to-end: snap_polygons succeeds on fb7e705c with all 12 panels

---

_Verified: 2026-04-19T06:15:00Z_
_Verifier: Claude (orchestrator, after human-reported failure and re-investigation)_
