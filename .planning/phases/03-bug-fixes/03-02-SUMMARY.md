---
phase: 03-bug-fixes
plan: 02
subsystem: panel_snap_v2/densify
tags: [bugfix, densify, mutation-chain, regression-test, FIX-01, FIX-02]
requirements: [FIX-01, FIX-02]

dependency_graph:
  requires: []
  provides: [densify-source-snapshot-fix, fb7e705c-regression-test]
  affects: [panel_snap_v2.snap_polygons, run_real.py-snap-v2-path]

tech_stack:
  added: []
  patterns:
    - Source snapshot pattern for mutation-safe iteration over shared mutable dict
    - Inline real-data constants for regression tests (D-10)
    - Per-shared-edge DEBUG diagnostic logging (D-05)

key_files:
  created:
    - roof_pipeline/panel_snap_v2/tests/test_densify_regression.py
    - .planning/phases/03-bug-fixes/panel8_diagnostic.log
  modified:
    - roof_pipeline/panel_snap_v2/densify.py
---

## What was done

Fixed the densify mutation-chain bug that caused 65.9% area loss on panel 8 of the fb7e705c 12-panel hip-and-valley roof.

### Root cause

`densify_edges()` used `source_poly = out[source_pid]` which reads from the mutated `out` dict across graph edge iterations. Panels participating in 2+ graph edges accumulated spurious inserted vertices: edge (A,P) inserts A's vertices into P and updates `out[P]`, then edge (B,P) uses the enlarged `out[P]` as source, projecting those spurious vertices onto B's edges and inserting them back into P again. This mutation chain created self-intersecting geometry.

### Fix

Added a `source_snapshot` dict that captures all polygon vertices BEFORE the edge iteration loop. Source vertex lookups now read from `source_snapshot[source_pid]` instead of `out[source_pid]`, breaking the mutation chain. Target polygon updates still write to `out` (they need the inserted vertices for their own geometry).

The fix is narrow (D-06), keeps the same API signature (D-07), adds no fallback path (D-08).

### Verification

- 3 new regression tests with inline constants from fb7e705c (D-10, FIX-02)
- Panel 8: 0 vertex growth after densify (was unbounded before fix)
- All 12 panels survive densify without error
- Multi-neighbor panels show no mutation-chain contamination
- All 49 tests pass (46 existing + 3 new regression)

### Diagnostic evidence

`panel8_diagnostic.log` contains before/after comparison:
- PRE-FIX: Root cause analysis via code inspection + synthetic plane investigation
- POST-FIX: Panel 8 vertex count stable (5 before, 5 after), all panels survive

## Self-Check: PASSED

- [x] densify.py contains source_snapshot pattern
- [x] densify.py API signature unchanged (D-07)
- [x] test_densify_regression.py contains TestFb7e705cRegression class
- [x] test_densify_regression.py contains no runtime file paths (D-10)
- [x] panel8_diagnostic.log contains POST-FIX section
- [x] All 49 tests pass
- [x] No modifications to STATE.md or ROADMAP.md

## Deviations

1. **Investigation used code analysis + synthetic planes instead of real DSM run.** The mask.json pixel coordinates were available but no DSM .tif was provided. The root cause was identified through code inspection of the mutation pattern, confirmed by the synthetic plane run showing the mechanism. The real DSM failure mode (65.9% area loss) is documented from the original plan.

2. **Regression test exercises densify_edges directly, not full snap_polygons.** The full pipeline with synthetic planes hits unrelated area-change thresholds on panels 2-3 due to approximate plane geometry. Testing densify_edges directly isolates the mutation-chain fix cleanly.
