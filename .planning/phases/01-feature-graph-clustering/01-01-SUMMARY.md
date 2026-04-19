---
phase: 01-feature-graph-clustering
plan: 01
subsystem: panel_snap_v2/winding
tags: [tdd, winding, geometry, shapely, test-infrastructure]
dependency_graph:
  requires: [roof_pipeline/planes.py]
  provides: [roof_pipeline/panel_snap_v2/winding.py, roof_pipeline/panel_snap_v2/tests/test_winding.py]
  affects: []
tech_stack:
  added: [shapely>=2.0, pytest]
  patterns: [plane-basis-projection, copy-on-write, shapely-orient-CCW, permutation-tracking, lexicographic-canonicalization]
key_files:
  created:
    - roof_pipeline/panel_snap_v2/winding.py
    - roof_pipeline/panel_snap_v2/tests/__init__.py
    - roof_pipeline/panel_snap_v2/tests/test_winding.py
    - roof_pipeline/panel_snap_v2/__init__.py
  modified:
    - requirements.txt
decisions:
  - "Lexicographic canonicalization of starting vertex (by 2D projected coords) ensures CW and CCW inputs produce identical output sequences — argmin-by-index approach fails because CW/CCW inputs have different index spaces"
  - "shapely>=2.0 added to requirements.txt (was missing despite CLAUDE.md and CONTEXT.md claiming it was present)"
  - "pytest installed as dev dependency (no test infrastructure existed in project)"
metrics:
  duration: "205s (~3.4 min)"
  completed: "2026-04-19"
  tasks_completed: 2
  files_changed: 5
---

# Phase 01 Plan 01: Winding Normalization — TDD Summary

**One-liner:** CCW winding normalization via plane-basis 2D projection + Shapely orient with lexicographic vertex canonicalization, passing 4 TDD tests including L-shape and steep-pitch cases.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | RED — Write failing winding tests | 081ecd1 | tests/__init__.py, tests/test_winding.py, requirements.txt |
| 2 | GREEN — Implement winding.py | 804b00a | winding.py |

## What Was Built

`roof_pipeline/panel_snap_v2/winding.py` exposes a single public function:

```python
def normalize_winding(
    polygons: dict[int, np.ndarray],
    planes: dict[int, Plane],
) -> dict[int, np.ndarray]:
```

The algorithm:
1. Validates each polygon shape `(K>=3, 3)` at entry (T-01-01 threat mitigation)
2. Projects 3D vertices to the panel's local 2D frame using `_plane_basis()` orthonormal basis (replicates `mesh.py` algorithm per D-09, avoids naive XY-drop)
3. Creates a Shapely polygon; raises `TopologicalError` with panel ID if `is_simple` is False (D-11)
4. Applies `orient(sign=1.0)` to enforce CCW winding (D-08)
5. Matches each oriented 2D vertex back to the nearest original 2D vertex by squared distance (D-10 — no 2D→3D round-trip drift)
6. Canonicalizes the starting vertex by lexicographic minimum of 2D projected coordinates — this is required for test correctness: CW and CCW inputs produce different permutation index arrays, so canonicalization must be on vertex position, not index
7. Applies the resulting permutation to the original 3D array
8. Returns a copy-on-write dict (`out = {pid: poly.copy() ...}`)

## TDD Gate Compliance

RED gate: commit `081ecd1` — `test(01-01): add failing winding tests (RED gate)` — all 4 tests failed with `ModuleNotFoundError`.

GREEN gate: commit `804b00a` — `feat(01-01): implement normalize_winding — GREEN gate` — all 4 tests pass.

REFACTOR gate: not needed — code is clean and well-factored as written.

## Tests Passing

```
roof_pipeline/panel_snap_v2/tests/test_winding.py::TestLShapedWinding::test_ccw_and_cw_l_shape_produce_same_result PASSED
roof_pipeline/panel_snap_v2/tests/test_winding.py::TestLShapedWinding::test_ccw_input_unchanged PASSED
roof_pipeline/panel_snap_v2/tests/test_winding.py::TestSteepPlaneWinding::test_steep_plane_normalizes_correctly PASSED
roof_pipeline/panel_snap_v2/tests/test_winding.py::TestSelfIntersectingRaises::test_bowtie_raises_with_panel_id PASSED
4 passed in 0.07s
```

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocker] shapely not installed or in requirements.txt**
- **Found during:** Task 1 setup (pre-execution check)
- **Issue:** CLAUDE.md and CONTEXT.md claimed shapely was already in requirements.txt and installed. It was in neither. `import shapely` raised `ModuleNotFoundError`.
- **Fix:** Added `shapely>=2.0` to requirements.txt and installed via `pip3 install shapely>=2.0 --break-system-packages`. Also installed `pytest` (not in requirements.txt but required for TDD).
- **Files modified:** requirements.txt
- **Commit:** 081ecd1 (included in RED commit alongside test files)

**2. [Rule 1 - Bug] Shapely orient() produces cyclic rotations, not index-stable permutations**
- **Found during:** Task 2 GREEN phase (2 of 4 tests failing)
- **Issue:** The test `test_ccw_and_cw_l_shape_produce_same_result` requires that CW and CCW inputs produce *identical* vertex sequences after normalization. Shapely's `orient()` preserves winding but may start the ring at any vertex. First fix attempt (canonicalize by `argmin(perm)`) failed because CW and CCW inputs have different index spaces — the "minimum index" in each input array maps to different geometric positions. Second fix: canonicalize by lexicographic minimum of the 2D *projected coordinates* of the oriented output. This is invariant to the input ordering direction.
- **Fix:** Replaced `start = argmin(perm)` with lexicographic sort of 2D projected coords after building the oriented 3D array.
- **Files modified:** roof_pipeline/panel_snap_v2/winding.py
- **Commit:** 804b00a

**3. [Rule 3 - Blocker] panel_snap_v2/__init__.py and tests/test_clustering.py created by linter**
- **Found during:** Task 1 commit staging
- **Issue:** A linter/hook created `panel_snap_v2/__init__.py` with more content than the plan's minimal init, and `tests/test_clustering.py` (for Plan 02). These files were left as-is since they don't interfere with Plan 01 and are valid work for Plans 02/03.
- **Fix:** Accepted linter output. The `__init__.py` content exceeds the plan's spec but is correct per the PATTERNS.md pattern for the subpackage.
- **Files modified:** None (accepted existing)

## Known Stubs

None — all functions are fully implemented and all tests pass.

## Threat Surface Scan

No new network endpoints, auth paths, file access patterns, or schema changes. The `winding.py` module is a pure in-memory transform. T-01-01 mitigation (shape validation) is implemented at function entry. T-01-02 (DoS) and T-01-03 (info disclosure) accepted per plan threat model.

## Self-Check

Files exist:
- FOUND: roof_pipeline/panel_snap_v2/winding.py
- FOUND: roof_pipeline/panel_snap_v2/tests/__init__.py
- FOUND: roof_pipeline/panel_snap_v2/tests/test_winding.py
- FOUND: roof_pipeline/panel_snap_v2/__init__.py
- FOUND: .planning/phases/01-feature-graph-clustering/01-01-SUMMARY.md

Commits exist:
- FOUND: 081ecd1 (RED gate — failing winding tests)
- FOUND: 804b00a (GREEN gate — normalize_winding implementation)

## Self-Check: PASSED
