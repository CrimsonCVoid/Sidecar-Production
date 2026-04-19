---
phase: 02-apex-solver-integration
verified: 2026-04-19T03:26:50Z
status: human_needed
score: 5/5 must-haves verified
overrides_applied: 0
human_verification:
  - test: "Run `python -m roof_pipeline.run_real <hip_roof_dsm.tif> <hip_roof_mask.npy> --snap-v2` on a real hip roof sample"
    expected: "PDF output has no visible triangular white gaps at the hip apex where 3+ panels converge"
    why_human: "Visual quality of hip apex rendering in PDF output cannot be verified programmatically -- requires human inspection of rendered geometry to confirm zero slivers"
  - test: "Open the generated snap_v2_features.json sidecar and inspect feature positions"
    expected: "Feature positions make geometric sense -- shared features have position_xyz coordinates that correspond to actual roof vertices"
    why_human: "Geometric plausibility of solved positions on a real roof sample requires spatial reasoning about the physical roof structure"
---

# Phase 2: Apex Solver + Integration Verification Report

**Phase Goal:** The complete `panel_snap_v2` engine is wired into `run_real.py` behind `--snap-v2`, solves valence-3+ apices via least-squares plane intersection, densifies shared edges, validates polygons with Shapely, emits `snap_v2_features.json`, passes all 7 correctness tests, and produces bit-for-bit identical output on the gable smoke test
**Verified:** 2026-04-19T03:26:50Z
**Status:** human_needed
**Re-verification:** No -- initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | All 7 named correctness tests pass (TEST-01 through TEST-07) including gable-unchanged, hip-apex-weld, ridge-weld, transitive-cluster, mixed-winding, self-intersecting-repair, and L-shaped-winding | VERIFIED | `pytest roof_pipeline/panel_snap_v2/tests/ -v` exits with 41 passed in 0.79s. All 7 named tests confirmed: TEST-01 (test_tier0_polygon_allclose), TEST-02 (test_hip_apex_four_panels_welds), TEST-03 (test_ridge_three_panels_welds), TEST-04 (test_transitive_cluster_above_tol), TEST-05 (test_mixed_winding_hip), TEST-06 (test_self_intersecting_input_repaired), TEST-07 (test_ccw_and_cw_l_shape_produce_same_result) |
| 2 | `run_real.py --snap-v2` completes and produces PDF with no visible gaps at hip apex | VERIFIED (automated) / NEEDS HUMAN (visual) | `run_real.py` has `--snap-v2` flag wired (line 70-71), routes through `snap_v2()` (line 117), writes JSON sidecar (lines 119-123). Pipeline completes on synthetic gable. Visual quality on hip roof sample requires human verification. |
| 3 | `snap_v2_features.json` is written with valid schema containing features (id, valence, position_xyz, panel_ids) and edges (panel_a, panel_b, feature_ids) | VERIFIED | Golden file `tests/golden/gable/features.json` confirms schema. Runtime spot-check confirms shared features (valence >= 2) have `position_xyz` populated with real coordinates; unshared features (valence == 1) have `position_xyz: null`. All schema fields present on every feature and edge. |
| 4 | Gable smoke test produces structurally equivalent output between v1 and v2 | VERIFIED | Spot-check confirms same panel IDs, same vertex shapes, max XY diff = 0.00e+00. Tiered golden-file tests pass: Tier 0 (polygon arrays at atol=1e-12), Tier 1 (JSON byte-identity), Tier 2 (mesh vertices at atol=1e-9 + exact face match). Cross-check tests confirm structural equivalence with v1 (same panel IDs, same shapes, matching XY after sort). |
| 5 | Malformed polygon JSON raises Pydantic validation error with actionable message | VERIFIED | Spot-check confirms: missing corners_pix rejected, empty corners rejected with "3 corners" in error message. 8 schema validation tests pass covering valid input, missing fields, wrong types, empty arrays, too-few vertices, missing panels key, non-numeric id, and multiple panels. `PanelsInput.model_validate` wired into `boundaries.py` at line 77. |

**Score:** 5/5 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `roof_pipeline/panel_snap_v2/solver.py` | Valence-aware apex solver | VERIFIED | 292 lines. Contains `solve_apices()`, `_solve_valence2()`, `_solve_valence3()`, `_solve_valence4plus()`, `_z_on_plane()`, `_COND_WARN = 1e8`, `_COND_FAIL = 1e12`. Proper copy-on-write, logging, condition-number guards. |
| `roof_pipeline/panel_snap_v2/schema.py` | Pydantic input validation models | VERIFIED | 35 lines. Contains `PanelCorners(BaseModel)` and `PanelsInput(BaseModel)` with `ConfigDict(strict=True, extra="forbid")` and `field_validator` for >= 3 corners. |
| `roof_pipeline/panel_snap_v2/densify.py` | Edge-walking densification | VERIFIED | 184 lines. Contains `densify_edges()`, `_z_on_plane()`, `_point_to_segment_dist_xy()`. Copy-on-write, parameter-t sorting, endpoint dedup. |
| `roof_pipeline/panel_snap_v2/validate.py` | Two-pass Shapely validation with repair | VERIFIED | 264 lines. Contains `validate_polygons()`, `_extract_largest_polygon()`, `_reconstruct_3d()`. Area thresholds `_AREA_WARN_THRESHOLD = 0.001`, `_AREA_FAIL_THRESHOLD = 0.01`, `_MULTI_AREA_RATIO_MIN = 0.95`. Two-pass pattern (solver=read-only, densify=repair). |
| `roof_pipeline/panel_snap_v2/__init__.py` | Complete pipeline orchestration | VERIFIED | 124 lines. 6-stage pipeline: winding -> graph -> solve -> validate(solver) -> densify -> validate(densify). Returns `tuple[dict, dict]`. Contains `_update_graph_positions()` for JSON sidecar. |
| `roof_pipeline/run_real.py` | CLI with --snap-v2 flag and JSON sidecar | VERIFIED | `--snap-v2` flag at line 70-71. V2 branch at line 115-123 routes through `snap_v2()`, writes `snap_v2_features.json`. V1 path preserved in else branch at lines 124-136. |
| `roof_pipeline/boundaries.py` | Pydantic validation at input boundary | VERIFIED | `from .panel_snap_v2.schema import PanelsInput` at line 12. `PanelsInput.model_validate(raw)` at line 77. |
| `requirements.txt` | pydantic>=2.0 dependency | VERIFIED | `pydantic>=2.0` at line 4. |
| `roof_pipeline/panel_snap_v2/tests/test_solver.py` | Solver unit tests | VERIFIED | 5 tests: TestHipApexWeld, TestRidgeWeld, TestValence2, TestConditionNumberFallback, TestConditionNumberHardFail. All pass. |
| `roof_pipeline/panel_snap_v2/tests/test_schema.py` | Schema validation tests | VERIFIED | 8 tests in TestSchemaValidation. All pass. |
| `roof_pipeline/panel_snap_v2/tests/test_densify.py` | Densification tests | VERIFIED | 3 tests in TestSharedEdgeDensification. All pass. |
| `roof_pipeline/panel_snap_v2/tests/test_validate.py` | Validation tests | VERIFIED | 8 tests: TestValidPolygon, TestSelfIntersectingRepair, TestSolverStageReadonly, TestAreaChangeThresholds (3), TestMultiPolygonHandling (2). All pass. |
| `roof_pipeline/panel_snap_v2/tests/test_smoke_gable.py` | Tiered golden-file test | VERIFIED | 5 tests in TestGableSmokeIdentity. All pass. |
| `roof_pipeline/panel_snap_v2/tests/conftest.py` | Shared fixtures + --regenerate-golden | VERIFIED | Contains `_make_plane()` and `pytest_addoption()` for `--regenerate-golden`. |
| `roof_pipeline/panel_snap_v2/tests/golden/gable/` | Golden files | VERIFIED | 4 files present: `polygons.npz`, `features.json`, `mesh_vertices.npy`, `mesh_faces.npy`. |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `__init__.py` | `solver.py` | `from .solver import solve_apices` | WIRED | Line 28. Called at line 108. |
| `__init__.py` | `densify.py` | `from .densify import densify_edges` | WIRED | Line 26. Called at line 115. |
| `__init__.py` | `validate.py` | `from .validate import validate_polygons` | WIRED | Line 29. Called at lines 112 and 118 (two passes). |
| `__init__.py` | `winding.py` | `from .winding import normalize_winding` | WIRED | Line 30. Called at line 102. |
| `__init__.py` | `graph.py` | `from .graph import build_feature_graph` | WIRED | Line 27. Called at line 105. |
| `run_real.py` | `__init__.py` | `from .panel_snap_v2 import snap_polygons as snap_v2` | WIRED | Line 31. Called at line 117 with destructuring `polygons, feature_graph = snap_v2(...)`. |
| `run_real.py` | JSON sidecar | `json.dump(feature_graph, f, ...)` | WIRED | Lines 121-122. Path: `args.out_dir / "snap_v2_features.json"`. |
| `boundaries.py` | `schema.py` | `from .panel_snap_v2.schema import PanelsInput` | WIRED | Line 12. Used at line 77: `PanelsInput.model_validate(raw)`. |
| `solver.py` | `clustering.py` | `from .clustering import cluster_vertices` | WIRED | Line 21. Called at line 218 in `solve_apices()`. |
| `validate.py` | `winding.py` | `from .winding import _project_to_2d, _plane_basis` | WIRED | Line 19. `_project_to_2d` called at line 189. `_plane_basis` called at line 70 in `_reconstruct_3d`. |
| `validate.py` | `shapely` | `from shapely.validation import make_valid` | WIRED | Line 16. Called at line 216. |
| `densify.py` | `planes.py` | `from ..planes import Plane` | WIRED | Line 16. Used in `_z_on_plane` helper. |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|--------------|--------|-------------------|--------|
| `__init__.py:snap_polygons` | `out` (polygons) | `solve_apices()` + `densify_edges()` + `validate_polygons()` | Yes -- transforms polygon arrays through 6-stage pipeline | FLOWING |
| `__init__.py:snap_polygons` | `graph` (feature graph) | `build_feature_graph()` + `_update_graph_positions()` | Yes -- graph built from clustering, positions filled from solved vertices | FLOWING |
| `run_real.py` | `feature_graph` | Destructured from `snap_v2()` return tuple | Yes -- written to JSON file via `json.dump` | FLOWING |
| `boundaries.py` | `validated` | `PanelsInput.model_validate(raw)` from JSON file | Yes -- Pydantic validates and returns parsed model | FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| snap_polygons returns tuple (dict, dict) | `type(snapped) == dict and type(graph) == dict` | True | PASS |
| Mesh builds from snapped output | `build_roof_mesh(snapped, planes)` | vertices=(8,3), faces=(4,3) | PASS |
| Feature graph has correct schema | All features have id, valence, position_xyz, panel_ids | Verified | PASS |
| Shared features have position_xyz populated | Features with valence >= 2 checked | All have float[3] values | PASS |
| Pydantic rejects malformed input | Missing corners_pix + empty corners | Both rejected with actionable errors | PASS |
| v1/v2 structural equivalence on gable | XY diff comparison after lexsort | Max diff = 0.00e+00 | PASS |
| All 41 tests pass | `pytest roof_pipeline/panel_snap_v2/tests/ -v` | 41 passed in 0.79s | PASS |
| All module exports importable | Import solve_apices, densify_edges, validate_polygons, PanelCorners, PanelsInput, snap_polygons | All callable/importable | PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-----------|-------------|--------|----------|
| TOPO-05 | 02-01 | Valence-2 XY centroid + per-plane Z | SATISFIED | `_solve_valence2()` in solver.py; `test_valence2_xy_centroid_per_plane_z` passes |
| TOPO-06 | 02-01 | Valence-3 closed-form 3-plane intersection | SATISFIED | `_solve_valence3()` in solver.py uses `np.linalg.solve`; `test_ridge_three_panels_welds` passes |
| TOPO-07 | 02-01 | Valence-4+ weighted least-squares | SATISFIED | `_solve_valence4plus()` in solver.py uses `np.linalg.lstsq` with `1/rms_residual` weights; `test_hip_apex_four_panels_welds` passes |
| TOPO-08 | 02-01 | Solved apex written back into every member panel | SATISFIED | solver.py lines 271-273: `out[pid][vi] = xyz` for each solved member |
| TOPO-09 | 02-03 | Edge-walking densify for shared edges | SATISFIED | `densify_edges()` in densify.py; 3 densify tests pass confirming vertex insertion, sorting, and dedup |
| TOPO-10 | 02-03 | Shapely validation pass with make_valid() repair | SATISFIED | `validate_polygons()` in validate.py; 8 validate tests pass covering two-pass, repair, area thresholds, MultiPolygon |
| VALID-01 | 02-02 | Pydantic validation at polygons_from_clicks boundary | SATISFIED | `PanelsInput.model_validate(raw)` at boundaries.py line 77; schema.py with strict mode |
| VALID-02 | 02-02 | Schema rejects malformed data with actionable errors | SATISFIED | 8 schema tests pass; error messages include "3 corners" for insufficient vertices |
| INTG-01 | 02-04 | --snap-v2 flag routes through panel_snap_v2 | SATISFIED | run_real.py line 70-71 adds flag; line 115-117 routes through snap_v2 |
| INTG-02 | 02-04 | snap_v2_features.json sidecar with schema | SATISFIED | run_real.py lines 119-123 writes JSON; golden file confirms schema with features and edges |
| INTG-03 | 02-04 | Downstream modules produce structurally equivalent output on gable | SATISFIED | test_tier0_v1_v2_structural_match and test_tier2_v1_v2_mesh_structural_match pass |
| TEST-01 | 02-04 | test_gable_two_panels_unchanged | SATISFIED | test_tier0_polygon_allclose passes against golden at atol=1e-12 |
| TEST-02 | 02-01 | test_hip_apex_four_panels_welds | SATISFIED | 4 panels at one point, all 4 share exact same (x,y,z) at atol=1e-9 |
| TEST-03 | 02-01 | test_ridge_three_panels_welds | SATISFIED | 3 panels at ridge point, all 3 share exact same (x,y,z) at atol=1e-9 |
| TEST-06 | 02-03 | test_self_intersecting_input_repaired | SATISFIED | Bowtie input repaired to Shapely-valid output |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `roof_pipeline/panel_snap_v2/graph.py` | 13-14, 113 | Stale comment "Phase 1: solver not yet implemented" and "position_xyz is always None" | Info | Comment is stale -- `_update_graph_positions` in `__init__.py` fills position_xyz at runtime after Phase 2. The initial None value in `build_feature_graph` is overwritten by the orchestrator. No behavioral impact. |

### Human Verification Required

### 1. Hip Roof Visual Quality

**Test:** Run `python -m roof_pipeline.run_real <hip_roof_dsm.tif> <hip_roof_mask.npy> --snap-v2` on a real hip roof sample with 3+ panels converging at apices.
**Expected:** The generated PDF has no visible triangular white gaps or slivers at hip/ridge apex convergence points. The mesh should show clean welding where panels meet.
**Why human:** Visual quality of rendered geometry at apex points -- whether slivers are truly eliminated -- requires human inspection of the output PDF. The automated tests verify geometric correctness (same xyz at apex) but not visual rendering quality.

### 2. Feature Graph Geometric Plausibility on Real Data

**Test:** Open the generated `snap_v2_features.json` sidecar from a real hip roof run and inspect that feature `position_xyz` values correspond to actual roof vertex locations.
**Expected:** Shared features at valence-3+ have position coordinates that make geometric sense for the physical roof structure (e.g., hip apex at the peak, ridge features along the ridge line).
**Why human:** Geometric plausibility of solved positions on a real roof sample requires spatial reasoning about the physical structure that automated tests on synthetic geometry cannot assess.

### Gaps Summary

No automated gaps found. All 5 observable truths are verified through code inspection, import checks, behavioral spot-checks, and the full 41-test suite passing. All 15 Phase 2 requirements (TOPO-05 through TOPO-10, VALID-01/02, INTG-01/02/03, TEST-01/02/03/06) are satisfied with implementation evidence.

The only outstanding items are visual verification of hip roof rendering quality and geometric plausibility on real (not synthetic) data, which cannot be verified programmatically.

One informational anti-pattern noted: a stale Phase 1 comment in `graph.py` that says "solver not yet implemented" -- this is cosmetic and has no behavioral impact since `_update_graph_positions()` correctly fills in position_xyz after the solver runs.

---

_Verified: 2026-04-19T03:26:50Z_
_Verifier: Claude (gsd-verifier)_
