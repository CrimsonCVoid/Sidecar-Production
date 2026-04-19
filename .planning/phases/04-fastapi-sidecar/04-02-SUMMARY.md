---
phase: 04-fastapi-sidecar
plan: 02
subsystem: api
tags: [refactor, run_pipeline, callable-entry-point, cli-wrapper]

# Dependency graph
requires:
  - phase: 02-apex-solver-integration
    provides: "panel_snap_v2 engine with snap_polygons() and build_feature_graph()"
provides:
  - "run_pipeline() callable function accepting data arrays and returning output paths"
  - "Thin main() CLI wrapper preserving existing CLI behavior"
  - "_load_dsm() at module level for API reuse"
affects: [04-03, 04-04, 05-labeling-dashboard]

# Tech tracking
tech-stack:
  added: []
  patterns: [callable-pipeline-entry-point, thin-cli-wrapper]

key-files:
  created: []
  modified:
    - roof_pipeline/run_real.py

key-decisions:
  - "NaN-safety mask clearing moved into run_pipeline() so both CLI and API get it automatically"
  - "estimate_number defaults to None in run_pipeline(); CLI passes args.dsm.stem as fallback, API passes request value"
  - "panels_json_path computed in main() and passed as Path|None; run_pipeline checks existence internally"

patterns-established:
  - "run_pipeline() as programmatic pipeline entry point: accepts loaded data arrays (dsm, mask, res_m), returns dict[str, Path] of output files"
  - "CLI main() is thin wrapper: argparse + file loading + run_pipeline() call"
  - "CLI-only features (--snap-v2-dryrun) stay in main(), not in run_pipeline()"

requirements-completed: [API-02]

# Metrics
duration: 2min
completed: 2026-04-19
---

# Phase 4 Plan 2: Pipeline Callable Refactor Summary

**Extracted run_pipeline() callable from main() for programmatic use by FastAPI /run-pipeline endpoint, preserving identical CLI behavior**

## Performance

- **Duration:** 2 min
- **Started:** 2026-04-19T16:27:34Z
- **Completed:** 2026-04-19T16:29:42Z
- **Tasks:** 1
- **Files modified:** 1

## Accomplishments
- Extracted pipeline stages (plane fits through shop drawings) into standalone `run_pipeline()` function with 14 parameters
- `run_pipeline()` accepts loaded data arrays (`dsm`, `mask`, `res_m`) and config kwargs, returns `dict[str, Path]` of all output file paths
- `main()` refactored to thin CLI wrapper: argparse setup, DSM/mask file loading, then delegates to `run_pipeline()`
- NaN-safety mask clearing moved into `run_pipeline()` so both CLI and API get it automatically
- `_load_dsm()` remains at module level for reuse by the API layer
- `--snap-v2-dryrun` early exit stays in `main()` (CLI-only feature)
- All 49 existing tests pass unchanged

## Task Commits

Each task was committed atomically:

1. **Task 1: Extract run_pipeline() from main() and wire main() as thin wrapper** - `d592d85` (refactor)

## Files Created/Modified
- `roof_pipeline/run_real.py` - Refactored: new `run_pipeline()` callable (lines 58-212), `main()` as thin CLI wrapper (lines 220-295), `_load_dsm()` unchanged at module level (lines 44-51)

## Decisions Made
- **NaN-safety location:** Moved the `np.where(np.isnan(dsm), 0, mask)` NaN-safety line from `main()` into `run_pipeline()`. Both CLI and API callers benefit from this safety check without needing to apply it themselves.
- **estimate_number default:** `run_pipeline()` defaults `estimate_number` to `None` and uses `"UNKNOWN"` as the fallback in `project_meta`. The CLI `main()` passes `args.estimate_number or args.dsm.stem` (preserving existing behavior). The API will pass whatever the request body contains.
- **panels_json_path handling:** `main()` computes `panels_json_path` as `Path | None` based on whether the JSON sidecar exists and `--no-clicks` is not set. `run_pipeline()` checks `panels_json_path is not None and panels_json_path.exists()` internally for safety.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None - the refactoring was straightforward since the plan specified exact line ranges and the function boundary was clean.

## Next Phase Readiness
- `run_pipeline()` is ready for the FastAPI `/run-pipeline` endpoint (Plan 04) to call directly
- `_load_dsm()` is available for the API to load DSM files from Supabase Storage paths
- The function signature matches what Plan 04's background task needs: data arrays in, file paths out
- All 49 existing tests confirm no regression

## Self-Check: PASSED

- [x] roof_pipeline/run_real.py exists on disk
- [x] Commit d592d85 exists in git log
- [x] 04-02-SUMMARY.md exists on disk
