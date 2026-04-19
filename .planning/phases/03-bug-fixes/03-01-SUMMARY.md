---
phase: 03-bug-fixes
plan: 01
subsystem: panel_snap_v2/schema
tags: [validation, pydantic, dedup, tdd, LABEL-01]
requirements: [LABEL-01]

dependency_graph:
  requires: []
  provides: [close-polygon-dedup-validator]
  affects: [boundaries.polygons_from_clicks, future-FastAPI-HTTP-path]

tech_stack:
  added: []
  patterns:
    - Pydantic field_validator chain (strip_close_polygon_duplicate before at_least_three_corners)
    - Module-level logger log = logging.getLogger(__name__) in schema.py
    - DEBUG-only logging for silent operational decisions

key_files:
  created: []
  modified:
    - roof_pipeline/panel_snap_v2/schema.py
    - roof_pipeline/panel_snap_v2/tests/test_schema.py

decisions:
  - "strip_close_polygon_duplicate placed BEFORE at_least_three_corners so dedup runs first, then count check catches edge case of 3-corner polygon with duplicate last"
  - "0.5px Euclidean pixel-space tolerance (per D-03 Claude's Discretion) catches both exact and sub-pixel near-duplicates from matplotlib auto-close"
  - "Module-level log = logging.getLogger(__name__) added to schema.py per project conventions (previously missing)"

metrics:
  duration: "85s"
  completed: "2026-04-19"
  tasks_completed: 1
  files_modified: 2
---

# Phase 03 Plan 01: Duplicate Close-Polygon Corner Dedup Summary

Silent close-polygon duplicate-corner removal via Pydantic field_validator on PanelCorners.corners_pix — strips last corner within 0.5px of first, protecting both CLI and future HTTP API paths from matplotlib auto-close artifacts.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| RED | Add failing tests for dedup | 92fbedd | tests/test_schema.py |
| GREEN | Implement strip_close_polygon_duplicate | 10ff56c | schema.py |

## What Was Built

Added `strip_close_polygon_duplicate` field_validator to `PanelCorners` in `schema.py`. The validator:

- Runs **before** `at_least_three_corners` (defined above it in class body — Pydantic v2 runs validators in definition order)
- Computes Euclidean distance between first and last corner in pixel space
- Strips the last corner if `dist_sq < 0.5**2` (0.5 pixel tolerance)
- Logs at DEBUG level only — no warning visible in normal INFO-level runs (D-03)
- Protects both CLI path (`polygons_from_clicks`) and future FastAPI HTTP path (same schema per D-01)

## Acceptance Criteria Verified

- [x] `strip_close_polygon_duplicate` defined in schema.py
- [x] `dist_sq < 0.5 ** 2` tolerance used
- [x] `log.debug` for DEBUG-only logging (D-03)
- [x] `return v[:-1]` strips only last corner (D-02)
- [x] `strip_close_polygon_duplicate` placed BEFORE `at_least_three_corners`
- [x] `TestDuplicateCornerDedup` class in test_schema.py
- [x] All 5 required test methods present and passing
- [x] `python -m pytest roof_pipeline/panel_snap_v2/tests/test_schema.py -x` exits 0 (13/13 passed)

## Test Results

```
13 passed in 0.10s
```

All 8 existing `TestSchemaValidation` tests continue to pass. All 5 new `TestDuplicateCornerDedup` tests pass.

## Deviations from Plan

**1. [Rule 2 - Missing critical functionality] Added module-level logger to schema.py**

- **Found during:** Task 1 (GREEN phase)
- **Issue:** schema.py had no module-level `log = logging.getLogger(__name__)` — required by project conventions and needed for the DEBUG log call in the new validator
- **Fix:** Added `import logging` and `log = logging.getLogger(__name__)` at module top per CLAUDE.md conventions
- **Files modified:** `roof_pipeline/panel_snap_v2/schema.py`
- **Commit:** 10ff56c

## Known Stubs

None.

## Threat Flags

No new security surface introduced. The dedup validator only operates on data already within the Pydantic validation boundary (JSON -> PanelsInput). Per the plan's threat model:

- T-03-01 mitigated: dedup strips only last corner matching first within 0.5px — cannot corrupt arbitrary vertices
- T-03-02 accepted: DEBUG log shows pixel distance only, no PII, not visible at production INFO level

## Self-Check: PASSED

- [x] `roof_pipeline/panel_snap_v2/schema.py` exists and contains `strip_close_polygon_duplicate`
- [x] `roof_pipeline/panel_snap_v2/tests/test_schema.py` exists and contains `TestDuplicateCornerDedup`
- [x] Commit 92fbedd (RED) exists in git log
- [x] Commit 10ff56c (GREEN) exists in git log
- [x] TDD gate compliance: `test(03-01)` commit precedes `feat(03-01)` commit
