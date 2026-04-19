---
phase: 02-apex-solver-integration
plan: 02
subsystem: validation
tags: [pydantic, input-validation, schema, boundaries, tdd]

# Dependency graph
requires:
  - phase: 01-feature-graph-clustering
    provides: "panel_snap_v2 subpackage structure"
provides:
  - "PanelCorners and PanelsInput Pydantic models in schema.py"
  - "Input validation at polygons_from_clicks boundary"
  - "pydantic>=2.0 dependency in requirements.txt"
affects: [02-04]

# Tech tracking
tech-stack:
  added: ["pydantic>=2.0"]
  patterns: ["Pydantic strict-mode validation at trust boundary", "ConfigDict(strict=True, extra='forbid') for HTTP-safe models"]

key-files:
  created:
    - roof_pipeline/panel_snap_v2/schema.py
    - roof_pipeline/panel_snap_v2/tests/test_schema.py
  modified:
    - roof_pipeline/boundaries.py
    - requirements.txt

key-decisions:
  - "ConfigDict(strict=True, extra='forbid') on both models per review notes -- prevents silent type coercion and extra field injection for Milestone 2 HTTP surface"
  - "Schema lives in panel_snap_v2/schema.py as single source of truth for CLI and future HTTP API (D-08)"
  - "Pydantic exception to TOPO-11 accepted per D-07 -- VALID-01 explicitly offers it and Milestone 2 FastAPI needs it"

patterns-established:
  - "Pydantic model_validate at input boundary before geometry processing"
  - "field_validator for domain-specific constraints (>= 3 corners for polygon)"

requirements-completed: [VALID-01, VALID-02]

# Metrics
duration: 2min
completed: 2026-04-19
---

# Phase 2 Plan 02: Pydantic Input Validation Summary

**Pydantic strict-mode schema at polygons_from_clicks boundary with 8-test TDD suite rejecting malformed panel JSON with actionable errors**

## Performance

- **Duration:** 2 min
- **Started:** 2026-04-19T02:50:03Z
- **Completed:** 2026-04-19T02:52:57Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments
- Created `schema.py` with `PanelCorners` and `PanelsInput` Pydantic models using strict mode and extra='forbid'
- Field validator enforces >= 3 corners per panel with actionable error message
- Wired `PanelsInput.model_validate()` into `boundaries.py` at the JSON load boundary
- Added `pydantic>=2.0` to `requirements.txt`
- All 25 tests pass (17 prior + 8 new schema tests)

## Task Commits

Each task was committed atomically:

1. **Task 1: RED -- Write failing schema validation tests** - `bf3a5c5` (test)
2. **Task 2: GREEN -- Implement schema.py, wire boundaries.py, update requirements.txt** - `0fb3534` (feat)

## TDD Gate Compliance

- RED gate: `bf3a5c5` (test commit -- 8 tests fail with ModuleNotFoundError)
- GREEN gate: `0fb3534` (feat commit -- all 25 tests pass)
- REFACTOR gate: not needed (code clean from initial implementation)

## Files Created/Modified
- `roof_pipeline/panel_snap_v2/schema.py` - PanelCorners and PanelsInput Pydantic models with strict mode, extra='forbid', and >= 3 corners validator
- `roof_pipeline/panel_snap_v2/tests/test_schema.py` - 8 tests: valid input, missing corners_pix, wrong type, empty corners, two-vertex polygon, missing panels key, non-numeric id, multiple panels
- `roof_pipeline/boundaries.py` - Added PanelsInput import and model_validate call at input boundary
- `requirements.txt` - Added pydantic>=2.0

## Decisions Made
- `ConfigDict(strict=True, extra='forbid')` on both `PanelCorners` and `PanelsInput` per 02-CONTEXT.md review notes -- strict mode prevents silent string-to-int coercion, extra='forbid' rejects unknown fields
- Kept the redundant `corners_pix.shape[0] < 3` guard in `boundaries.py` as belt-and-suspenders safety (Pydantic now enforces this but the guard prevents regressions if someone bypasses schema)
- Pydantic is an accepted exception to TOPO-11 (no new deps rule) per D-07, because VALID-01 explicitly offers it and Milestone 2 FastAPI needs it natively

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None.

## User Setup Required
None - pydantic installed via pip, no external service configuration.

## Next Phase Readiness
- Schema models ready for import by future FastAPI endpoints in Milestone 2
- `polygons_from_clicks` now validates input before geometry processing
- All 25 tests green -- safe to build on

---
*Phase: 02-apex-solver-integration*
*Completed: 2026-04-19*

## Self-Check: PASSED

- All 4 files exist on disk (schema.py, test_schema.py, boundaries.py, requirements.txt)
- Both task commits found in git log (bf3a5c5, 0fb3534)
- All 25 tests pass (17 prior + 8 new)
